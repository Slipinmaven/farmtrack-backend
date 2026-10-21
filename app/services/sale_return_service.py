from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.sale_delivery_repository import SaleDeliveryRepository
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_payment_repository import TransactionPaymentRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    InventoryMovementType,
    ProductType,
    SaleReturnType,
    NotificationEventType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.sale_delivery import SaleDeliveryAllocationResponse
from app.schemas.sale_return import (
    SaleReturnCreateRequest,
    SaleReturnHistoryResponse,
    SaleReturnItemResponse,
    SaleReturnResponse,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService
from app.services.transaction_balance import (
    calculate_transaction_balance,
    get_settlement_adjustment,
)
from app.services.transaction_pricing import (
    calculate_prorated_return_credit,
    calculate_sale_return_credit_total,
)

logger = get_application_logger()


class SaleReturnService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        product_repository: ProductRepository,
        sale_delivery_repository: SaleDeliveryRepository,
        sale_return_repository: SaleReturnRepository,
        transaction_payment_repository: TransactionPaymentRepository,
        transaction_refund_repository: TransactionRefundRepository,
        chicken_batch_repository: ChickenBatchRepository,
        block_repository: BlockRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        inventory_service: InventoryService,
        notification_outbox_repository: NotificationOutboxRepository | None = None,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.product_repository = product_repository
        self.sale_delivery_repository = sale_delivery_repository
        self.sale_return_repository = sale_return_repository
        self.transaction_payment_repository = transaction_payment_repository
        self.transaction_refund_repository = transaction_refund_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.inventory_service = inventory_service
        self.notification_outbox_repository = notification_outbox_repository

    async def create_return(
        self,
        farm_id: UUID,
        transaction_id: UUID,
        request: SaleReturnCreateRequest,
        user_id: UUID | None = None,
    ) -> SaleReturnResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Sale transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.SALE:
                raise ConflictError("Returns can only be recorded for sale transactions.")
            if transaction.status == TransactionStatus.CANCELLED:
                raise ConflictError("A cancelled sale cannot receive additional returns.")

            transaction_items = {item.id: item for item in transaction.items}
            delivered_by_item = (
                await self.sale_delivery_repository.get_delivered_quantities_by_transaction(
                    transaction_id
                )
            )
            delivered_by_batch = (
                await self.sale_delivery_repository.get_delivered_quantities_by_batch(
                    transaction_id
                )
            )
            cancelled_by_item = await self.sale_return_repository.get_quantities_by_type(
                transaction_id,
                SaleReturnType.UNDELIVERED_CANCELLED.value,
            )
            returned_by_item = await self.sale_return_repository.get_quantities_by_type(
                transaction_id,
                SaleReturnType.DELIVERED_RETURN.value,
            )
            returned_by_batch = (
                await self.sale_return_repository.get_returned_quantities_by_batch(
                    transaction_id
                )
            )
            credited_quantities = (
                await self.sale_return_repository.get_credited_quantities_by_item(
                    transaction_id
                )
            )
            credited_amounts = {
                item_id: calculate_prorated_return_credit(
                    Decimal(str(transaction_items[item_id].total_amount)),
                    quantity,
                    self._ordered_quantity(transaction_items[item_id]),
                )
                for item_id, quantity in credited_quantities.items()
                if item_id in transaction_items
            }

            block_ids = {
                allocation.block_id
                for item in request.items
                for allocation in item.batch_allocations
            }
            blocks = {}
            for block_id in sorted(block_ids, key=str):
                block = await self.block_repository.get_by_id_for_update(
                    farm_id,
                    block_id,
                )
                if block is None:
                    raise ResourceNotFoundError("Return destination block not found.")
                if not block.is_active:
                    raise ConflictError("Returned chickens must go to an active block.")
                blocks[block_id] = block

            plans = []
            stock_increments: defaultdict[tuple[UUID, UUID], int] = defaultdict(int)
            batch_returns: defaultdict[tuple[UUID, UUID], int] = defaultdict(int)
            block_increments: defaultdict[UUID, int] = defaultdict(int)
            requested_credit_total = Decimal("0.00")
            has_chicken_return = False

            for return_item in request.items:
                transaction_item = transaction_items.get(return_item.transaction_item_id)
                if transaction_item is None:
                    raise ResourceNotFoundError(
                        "A transaction item was not found on this sale."
                    )
                product = await self.product_repository.get_by_id(
                    farm_id,
                    transaction_item.product_id,
                )
                if product is None:
                    raise ResourceNotFoundError("Sale product not found.")

                ordered_quantity = self._ordered_quantity(transaction_item)
                quantity = Decimal(return_item.quantity)
                is_chicken = product.product_type == ProductType.CHICKENS
                has_chicken_return = has_chicken_return or is_chicken
                if is_chicken and ordered_quantity != ordered_quantity.to_integral_value():
                    raise ConflictError(
                        "The sale item does not represent a whole number of chickens."
                    )
                if request.return_type == SaleReturnType.UNDELIVERED_CANCELLED:
                    if not is_chicken:
                        raise ConflictError(
                            "Only chicken sales track undelivered quantities; "
                            "record a delivered return for other products."
                        )
                    outstanding_quantity = (
                        ordered_quantity
                        - delivered_by_item.get(transaction_item.id, Decimal("0"))
                        - cancelled_by_item.get(transaction_item.id, Decimal("0"))
                    )
                    if quantity > outstanding_quantity:
                        raise ConflictError(
                            f"Cannot cancel {quantity} chickens; only "
                            f"{outstanding_quantity} remain undelivered."
                        )
                else:
                    delivered_quantity = (
                        delivered_by_item.get(
                            transaction_item.id,
                            Decimal("0"),
                        )
                        if is_chicken
                        else ordered_quantity
                    )
                    returnable_quantity = (
                        delivered_quantity
                        - returned_by_item.get(transaction_item.id, Decimal("0"))
                    )
                    if quantity > returnable_quantity:
                        raise ConflictError(
                            f"Cannot return {quantity} chickens; only "
                            f"{returnable_quantity} were delivered and not previously returned."
                        )

                resolved_allocations = []
                if request.return_type == SaleReturnType.DELIVERED_RETURN:
                    if is_chicken and quantity != quantity.to_integral_value():
                        raise ConflictError("Chicken returns must be whole chickens.")
                    if is_chicken and not return_item.batch_allocations:
                        raise ConflictError(
                            "Chicken returns require batch and block allocations."
                        )
                    if not is_chicken and return_item.batch_allocations:
                        raise ConflictError(
                            "Only chicken returns can have batch and block allocations."
                        )
                    allocated_quantity = 0
                    for allocation in sorted(
                        return_item.batch_allocations,
                        key=lambda entry: (str(entry.batch_id), str(entry.block_id)),
                    ):
                        batch = await self.chicken_batch_repository.get_by_id(
                            farm_id,
                            allocation.batch_id,
                        )
                        if batch is None:
                            raise ResourceNotFoundError("Return batch not found.")
                        if batch.status != ChickenBatchStatus.ACTIVE:
                            raise ConflictError(
                                "Returned chickens must be assigned to an active batch."
                            )
                        if (
                            transaction_item.chicken_type is not None
                            and batch.chicken_type != transaction_item.chicken_type
                        ):
                            raise ConflictError(
                                "Return batch chicken type does not match the sale item."
                            )
                        if allocation.block_id not in blocks:
                            raise ResourceNotFoundError("Return destination block not found.")

                        batch_returns[(transaction_item.id, allocation.batch_id)] += (
                            allocation.quantity
                        )
                        stock_increments[(allocation.batch_id, allocation.block_id)] += (
                            allocation.quantity
                        )
                        block_increments[allocation.block_id] += allocation.quantity
                        allocated_quantity += allocation.quantity
                        resolved_allocations.append(allocation)

                    if is_chicken and Decimal(allocated_quantity) != quantity:
                        raise ConflictError(
                            "Return allocations must equal the returned quantity."
                        )

                cumulative_credited_quantity = (
                    credited_quantities.get(transaction_item.id, Decimal("0"))
                    + quantity
                )
                cumulative_credit = calculate_prorated_return_credit(
                    transaction_item.total_amount,
                    cumulative_credited_quantity,
                    ordered_quantity,
                )
                credit_amount = cumulative_credit - credited_amounts.get(
                    transaction_item.id,
                    Decimal("0.00"),
                )
                requested_credit_total += credit_amount
                plans.append(
                    (
                        return_item,
                        transaction_item,
                        product,
                        credit_amount,
                        resolved_allocations,
                    )
                )

            for (transaction_item_id, batch_id), quantity in batch_returns.items():
                delivered_quantity = delivered_by_batch.get(
                    (transaction_item_id, batch_id),
                    0,
                )
                previously_returned = returned_by_batch.get(
                    (transaction_item_id, batch_id),
                    0,
                )
                if quantity > delivered_quantity - previously_returned:
                    raise ConflictError(
                        "Return batch allocation exceeds the quantity previously delivered from that batch."
                    )

            for block_id, quantity in block_increments.items():
                block = blocks[block_id]
                current_quantity = await self.batch_block_repository.get_total_quantity_by_block(
                    block_id
                )
                maximum_quantity = block.capacity + block.over_capacity_limit
                if current_quantity + quantity > maximum_quantity:
                    raise ConflictError(
                        f"Returning these chickens would exceed block '{block.name}' capacity."
                    )

            stock_rows = {}
            for batch_id, block_id in sorted(
                stock_increments,
                key=lambda pair: (str(pair[0]), str(pair[1])),
            ):
                stock_rows[(batch_id, block_id)] = (
                    await self.batch_block_repository.get_by_batch_and_block(
                        batch_id,
                        block_id,
                    )
                )

            sale_return = await self.sale_return_repository.create_return(
                {
                    "transaction_id": transaction_id,
                    "return_type": request.return_type.value,
                    "return_date": request.return_date,
                    "return_time": request.return_time,
                    "reason": request.reason.strip(),
                    "notes": request.notes,
                }
            )
            response_items = []
            for (
                return_item,
                transaction_item,
                product,
                credit_amount,
                allocations,
            ) in plans:
                saved_item = await self.sale_return_repository.create_item(
                    {
                        "sale_return_id": sale_return.id,
                        "transaction_item_id": transaction_item.id,
                        "quantity": Decimal(return_item.quantity),
                        "credit_amount": credit_amount,
                    }
                )
                allocation_responses = []
                for allocation in allocations:
                    await self.sale_return_repository.create_allocation(
                        {
                            "sale_return_item_id": saved_item.id,
                            "batch_id": allocation.batch_id,
                            "block_id": allocation.block_id,
                            "quantity": allocation.quantity,
                        }
                    )
                    allocation_responses.append(
                        SaleDeliveryAllocationResponse(
                            batch_id=allocation.batch_id,
                            block_id=allocation.block_id,
                            quantity=allocation.quantity,
                        )
                    )
                response_items.append(
                    SaleReturnItemResponse(
                        id=saved_item.id,
                        transaction_item_id=transaction_item.id,
                        product_id=transaction_item.product_id,
                        product_name=getattr(product, "name", None),
                        quantity=saved_item.quantity,
                        credit_amount=saved_item.credit_amount,
                        batch_allocations=allocation_responses,
                    )
                )
                if request.return_type == SaleReturnType.DELIVERED_RETURN:
                    await self.inventory_service.append_movement(
                        farm_id=farm_id,
                        user_id=user_id,
                        product_id=transaction_item.product_id,
                        quantity_delta=Decimal(str(return_item.quantity)),
                        movement_type=InventoryMovementType.CUSTOMER_RETURN,
                        occurred_on=request.return_date,
                        notes=f"Customer return: {request.reason.strip()}",
                        source_type="sale_return",
                        source_id=sale_return.id,
                        source_item_id=saved_item.id,
                    )

            for key, quantity in stock_increments.items():
                batch_block = stock_rows[key]
                if batch_block is None:
                    await self.batch_block_repository.create(
                        {
                            "batch_id": key[0],
                            "block_id": key[1],
                            "quantity": quantity,
                        }
                    )
                else:
                    batch_block.quantity += quantity
                    await self.batch_block_repository.update(batch_block)

            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.SALE_RETURN_CREATED,
                entity_type=ActivityEntityType.SALE_RETURN,
                entity_id=sale_return.id,
                details={
                    "transaction_id": str(transaction_id),
                    "transaction_type": transaction.transaction_type.value,
                    "reference_number": getattr(transaction, "reference_number", None),
                    "contact_id": (
                        str(transaction.contact_id)
                        if getattr(transaction, "contact_id", None) is not None
                        else None
                    ),
                    "return_type": request.return_type.value,
                    "return_date": request.return_date.isoformat(),
                    "reason": request.reason.strip(),
                    "notes": request.notes,
                    "item_count": len(response_items),
                    "quantity": str(sum(item.quantity for item in response_items)),
                    "credit_total": str(requested_credit_total),
                    "items": [
                        {
                            "product_name": item.product_name,
                            "quantity_returned": str(item.quantity),
                            "credit_amount": str(item.credit_amount),
                            "allocations": [
                                {
                                    "block_name": blocks[
                                        allocation.block_id
                                    ].name,
                                    "quantity": str(allocation.quantity),
                                }
                                for allocation in item.batch_allocations
                            ],
                        }
                        for item in response_items
                    ],
                },
            )
            if (
                self.notification_outbox_repository is not None
                and has_chicken_return
            ):
                await self.notification_outbox_repository.enqueue(
                    farm_id=farm_id,
                    event_type=NotificationEventType.CHICKEN_RETURN_RECORDED.value,
                    payload={"return_id": str(sale_return.id)},
                    dedupe_key=f"chicken-return.recorded:{sale_return.id}",
                )

            payments = await self.transaction_payment_repository.list_by_transaction(
                transaction_id
            )
            amount_received = sum(
                (payment.amount for payment in payments),
                Decimal("0.00"),
            )
            amount_refunded = (
                await self.transaction_refund_repository.get_total_by_transaction(
                    transaction_id
                )
            )
            credited_quantities = (
                await self.sale_return_repository.get_credited_quantities_by_item(
                    transaction_id
                )
            )
            total_credits = calculate_sale_return_credit_total(
                transaction.items,
                credited_quantities,
            )
            transaction_total = sum(
                (item.total_amount for item in transaction.items),
                Decimal("0.00"),
            )
            balances = calculate_transaction_balance(
                transaction_total,
                amount_received,
                amount_refunded,
                total_credits,
                settlement_adjustment=get_settlement_adjustment(transaction),
            )

            await self.unit_of_work.commit()
            logger.info(
                "sale_return_created",
                extra={
                    "event": "sale_return_created",
                    "farm_id": farm_id,
                    "user_id": user_id,
                    "transaction_id": transaction_id,
                    "sale_return_id": sale_return.id,
                    "return_type": request.return_type.value,
                    "item_count": len(response_items),
                    "credit_total": str(requested_credit_total),
                },
            )
            return SaleReturnResponse(
                id=sale_return.id,
                transaction_id=transaction_id,
                return_type=request.return_type,
                return_date=sale_return.return_date,
                return_time=sale_return.return_time,
                reason=sale_return.reason,
                notes=sale_return.notes,
                created_at=sale_return.created_at,
                credit_total=requested_credit_total,
                adjusted_transaction_total=balances.adjusted_transaction_total,
                amount_paid=balances.amount_paid,
                balance_due=balances.balance_due,
                credit_balance=balances.credit_balance,
                items=response_items,
            )

    async def list_returns(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[SaleReturnHistoryResponse]:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Sale transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.SALE:
                raise ConflictError("Return history is only available for sales.")

            returns = await self.sale_return_repository.list_by_transaction(
                transaction_id
            )
            transaction_items = {item.id: item for item in transaction.items}
            responses = []
            credited_quantities: defaultdict[UUID, Decimal] = defaultdict(
                lambda: Decimal("0")
            )
            credited_amounts: defaultdict[UUID, Decimal] = defaultdict(
                lambda: Decimal("0.00")
            )
            for sale_return in returns:
                response_items = []
                return_credit_total = Decimal("0.00")
                for item in sale_return.items:
                    transaction_item = transaction_items[item.transaction_item_id]
                    product = await self.product_repository.get_by_id(
                        farm_id,
                        transaction_item.product_id,
                    )
                    if product is None:
                        raise ResourceNotFoundError("Sale product not found.")
                    credited_quantities[item.transaction_item_id] += item.quantity
                    cumulative_credit = calculate_prorated_return_credit(
                        transaction_item.total_amount,
                        credited_quantities[item.transaction_item_id],
                        self._ordered_quantity(transaction_item),
                    )
                    credit_amount = (
                        cumulative_credit - credited_amounts[item.transaction_item_id]
                    )
                    credited_amounts[item.transaction_item_id] = cumulative_credit
                    return_credit_total += credit_amount
                    response_items.append(
                        SaleReturnItemResponse(
                            id=item.id,
                            transaction_item_id=item.transaction_item_id,
                            product_id=product.id,
                            product_name=getattr(product, "name", None),
                            quantity=item.quantity,
                            credit_amount=credit_amount,
                            batch_allocations=[
                                SaleDeliveryAllocationResponse(
                                    batch_id=allocation.batch_id,
                                    block_id=allocation.block_id,
                                    quantity=allocation.quantity,
                                )
                                for allocation in item.batch_allocations
                            ],
                        )
                    )
                responses.append(
                    SaleReturnHistoryResponse(
                        id=sale_return.id,
                        transaction_id=sale_return.transaction_id,
                        return_type=SaleReturnType(sale_return.return_type),
                        return_date=sale_return.return_date,
                        return_time=sale_return.return_time,
                        reason=sale_return.reason,
                        notes=sale_return.notes,
                        created_at=sale_return.created_at,
                        credit_total=return_credit_total,
                        items=response_items,
                    )
                )
            return responses

    @staticmethod
    def _ordered_quantity(transaction_item) -> Decimal:
        return (
            Decimal(str(transaction_item.quantity))
            * Decimal(str(transaction_item.conversion_factor))
        )

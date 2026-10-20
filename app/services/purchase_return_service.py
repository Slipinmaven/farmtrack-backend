from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_transaction_item_repository import (
    ChickenTransactionItemRepository,
)
from app.repositories.product_repository import ProductRepository
from app.repositories.purchase_receipt_item_repository import PurchaseReceiptItemRepository
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_replacement_repository import PurchaseReplacementRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.transaction_payment_repository import TransactionPaymentRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.chicken_purchase import BlockAllocationResponse
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    InventoryMovementType,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.purchase_return import (
    PurchaseReturnCreateRequest,
    PurchaseReturnHistoryResponse,
    PurchaseReturnItemResponse,
    PurchaseReturnResponse,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService
from app.services.transaction_balance import (
    calculate_transaction_balance,
    get_settlement_adjustment,
)

logger = get_application_logger()


class PurchaseReturnService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        product_repository: ProductRepository,
        chicken_transaction_item_repository: ChickenTransactionItemRepository,
        receipt_item_repository: PurchaseReceiptItemRepository,
        purchase_return_repository: PurchaseReturnRepository,
        supplier_refund_repository: PurchaseSupplierRefundRepository,
        replacement_repository: PurchaseReplacementRepository,
        payment_repository: TransactionPaymentRepository,
        block_repository: BlockRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        inventory_service: InventoryService,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.product_repository = product_repository
        self.chicken_transaction_item_repository = chicken_transaction_item_repository
        self.receipt_item_repository = receipt_item_repository
        self.purchase_return_repository = purchase_return_repository
        self.supplier_refund_repository = supplier_refund_repository
        self.replacement_repository = replacement_repository
        self.payment_repository = payment_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.inventory_service = inventory_service

    async def create_return(
        self,
        farm_id: UUID,
        transaction_id: UUID,
        request: PurchaseReturnCreateRequest,
        user_id: UUID | None = None,
    ) -> PurchaseReturnResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Purchase transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.PURCHASE:
                raise ConflictError("Chicken returns can only be recorded for purchases.")
            if transaction.status == TransactionStatus.CANCELLED:
                raise ConflictError("A cancelled purchase cannot receive returns.")

            transaction_items = {item.id: item for item in transaction.items}
            received_quantities = (
                await self.receipt_item_repository.get_received_quantities_by_transaction(
                    transaction_id
                )
            )
            returned_quantities = (
                await self.purchase_return_repository.get_returned_quantities(
                    transaction_id
                )
            )
            previous_credits = (
                await self.purchase_return_repository.get_credit_amounts_by_item(
                    transaction_id
                )
            )

            resolved_items = []
            planned_stock: defaultdict[tuple[UUID, UUID], int] = defaultdict(int)
            block_ids = {
                allocation.block_id
                for item in request.items
                for allocation in item.block_allocations
            }
            blocks = {}
            for block_id in sorted(block_ids, key=str):
                block = await self.block_repository.get_by_id_for_update(
                    farm_id,
                    block_id,
                )
                if block is None:
                    raise ResourceNotFoundError("Return block not found for this farm.")
                blocks[block_id] = block

            for item_request in request.items:
                transaction_item = transaction_items.get(item_request.transaction_item_id)
                if transaction_item is None:
                    raise ResourceNotFoundError(
                        "A transaction item was not found on this purchase."
                    )
                product = await self.product_repository.get_by_id(
                    farm_id,
                    transaction_item.product_id,
                )
                if product is None:
                    raise ResourceNotFoundError("Purchase product not found.")
                is_chicken = product.product_type == ProductType.CHICKENS
                linked_batch = None
                if is_chicken:
                    linked_batch = (
                        await self.chicken_transaction_item_repository.get_by_transaction_item(
                            transaction_item.id
                        )
                    )
                    if linked_batch is None:
                        raise ConflictError(
                            "This purchase item has not been assigned to a chicken batch."
                        )
                    if linked_batch.batch.status != ChickenBatchStatus.ACTIVE:
                        raise ConflictError(
                            "Chickens can only be returned from an active batch."
                        )

                ordered_quantity = self._base_quantity(transaction_item)
                if is_chicken and ordered_quantity != ordered_quantity.to_integral_value():
                    raise ConflictError(
                        "The purchase item does not represent a whole number of chickens."
                    )
                received_quantity = (
                    received_quantities.get(
                        transaction_item.id,
                        Decimal("0"),
                    )
                    if is_chicken
                    else ordered_quantity
                )
                already_returned = returned_quantities.get(
                    transaction_item.id,
                    Decimal("0"),
                )
                return_quantity = Decimal(item_request.quantity_returned)
                returnable_quantity = min(ordered_quantity, received_quantity) - already_returned
                if return_quantity > returnable_quantity:
                    raise ConflictError(
                        f"Cannot return {return_quantity} "
                        f"{getattr(product, 'name', 'units')}; only "
                        f"{returnable_quantity} were received and not previously returned."
                    )

                if is_chicken:
                    if return_quantity != return_quantity.to_integral_value():
                        raise ConflictError("Chicken returns must be whole chickens.")
                    if not item_request.block_allocations:
                        raise ConflictError(
                            "Chicken purchase returns require block allocations."
                        )
                    for allocation in item_request.block_allocations:
                        planned_stock[(linked_batch.batch_id, allocation.block_id)] += (
                            allocation.quantity
                        )
                    if sum(
                        allocation.quantity
                        for allocation in item_request.block_allocations
                    ) != return_quantity:
                        raise ConflictError(
                            "Block allocations must equal the returned chicken quantity."
                        )
                elif item_request.block_allocations:
                    raise ConflictError(
                        "Only chicken returns can have block allocations."
                    )

                cumulative_returned = already_returned + return_quantity
                cumulative_credit = (
                    transaction_item.total_amount
                    * cumulative_returned
                    / ordered_quantity
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                credit_amount = cumulative_credit - previous_credits.get(
                    transaction_item.id,
                    Decimal("0.00"),
                )
                resolved_items.append(
                    (
                        item_request,
                        transaction_item,
                        product,
                        linked_batch,
                        credit_amount,
                    )
                )

            stock_rows = {}
            for (batch_id, block_id), requested_quantity in sorted(
                planned_stock.items(),
                key=lambda entry: (str(entry[0][0]), str(entry[0][1])),
            ):
                batch_block = await self.batch_block_repository.get_by_batch_and_block(
                    batch_id,
                    block_id,
                )
                if batch_block is None or batch_block.quantity < requested_quantity:
                    raise ConflictError(
                        f"Not enough stock in the selected block for batch '{batch_id}'."
                    )
                stock_rows[(batch_id, block_id)] = batch_block

            purchase_return = await self.purchase_return_repository.create_return(
                {
                    "transaction_id": transaction_id,
                    "return_date": request.return_date,
                    "return_time": request.return_time,
                    "reason": request.reason,
                    "notes": request.notes,
                }
            )
            response_items = []
            for (
                item_request,
                transaction_item,
                product,
                linked_batch,
                credit_amount,
            ) in resolved_items:
                return_item = await self.purchase_return_repository.create_item(
                    {
                        "purchase_return_id": purchase_return.id,
                        "transaction_item_id": transaction_item.id,
                        "quantity": Decimal(item_request.quantity_returned),
                        "credit_amount": credit_amount,
                    }
                )
                block_allocations = []
                if linked_batch is not None:
                    for allocation in item_request.block_allocations:
                        await self.purchase_return_repository.create_allocation(
                            {
                                "purchase_return_item_id": return_item.id,
                                "batch_id": linked_batch.batch_id,
                                "block_id": allocation.block_id,
                                "quantity": allocation.quantity,
                            }
                        )
                        block_allocations.append(
                            BlockAllocationResponse(
                                block_id=allocation.block_id,
                                quantity=allocation.quantity,
                            )
                        )
                response_items.append(
                    PurchaseReturnItemResponse(
                        id=return_item.id,
                        transaction_item_id=transaction_item.id,
                        product_id=product.id,
                        product_name=getattr(product, "name", None),
                        batch_id=linked_batch.batch_id if linked_batch else None,
                        chicken_type=(
                            linked_batch.batch.chicken_type
                            if linked_batch
                            else None
                        ),
                        quantity_returned=return_item.quantity,
                        credit_amount=return_item.credit_amount,
                        block_allocations=block_allocations,
                    )
                )
                await self.inventory_service.append_movement(
                    farm_id=farm_id,
                    user_id=user_id,
                    product_id=product.id,
                    quantity_delta=-Decimal(str(item_request.quantity_returned)),
                    movement_type=InventoryMovementType.SUPPLIER_RETURN,
                    occurred_on=request.return_date,
                    notes=f"Supplier return: {request.reason}",
                    source_type="purchase_return",
                    source_id=purchase_return.id,
                    source_item_id=return_item.id,
                )

            for key, quantity in planned_stock.items():
                batch_block = stock_rows[key]
                batch_block.quantity -= quantity
                await self.batch_block_repository.update(batch_block)

            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.PURCHASE_RETURN_CREATED,
                entity_type=ActivityEntityType.PURCHASE_RETURN,
                entity_id=purchase_return.id,
                details={
                    "transaction_id": str(transaction_id),
                    "transaction_type": transaction.transaction_type.value,
                    "reference_number": getattr(transaction, "reference_number", None),
                    "contact_id": (
                        str(transaction.contact_id)
                        if getattr(transaction, "contact_id", None) is not None
                        else None
                    ),
                    "return_reason": request.reason,
                    "return_date": request.return_date.isoformat(),
                    "notes": request.notes,
                    "item_count": len(response_items),
                    "quantity": str(
                        sum(item.quantity_returned for item in response_items)
                    ),
                    "credit_total": str(
                        sum(item.credit_amount for item in response_items)
                    ),
                    "items": [
                        {
                            "product_name": item.product_name,
                            "chicken_type": (
                                item.chicken_type.value
                                if item.chicken_type is not None
                                else None
                            ),
                            "quantity_returned": str(item.quantity_returned),
                            "credit_amount": str(item.credit_amount),
                            "allocations": [
                                {
                                    "block_name": blocks[
                                        allocation.block_id
                                    ].name,
                                    "quantity": str(allocation.quantity),
                                }
                                for allocation in item.block_allocations
                            ],
                        }
                        for item in response_items
                    ],
                },
            )
            await self.unit_of_work.flush()
            balances = await self._purchase_balances(transaction)
            return_credit_remaining = await self._return_credit_remaining(
                transaction_id,
                balances.credit_balance,
            )
            await self.unit_of_work.commit()

            credit_total = sum(
                (item.credit_amount for item in response_items),
                Decimal("0.00"),
            )
            logger.info(
                "purchase_return_created",
                extra={
                    "event": "purchase_return_created",
                    "farm_id": farm_id,
                    "user_id": user_id,
                    "transaction_id": transaction_id,
                    "purchase_return_id": purchase_return.id,
                    "item_count": len(response_items),
                    "credit_total": str(credit_total),
                },
            )
            return PurchaseReturnResponse(
                id=purchase_return.id,
                transaction_id=transaction_id,
                return_date=purchase_return.return_date,
                return_time=purchase_return.return_time,
                reason=purchase_return.reason,
                notes=purchase_return.notes,
                created_at=purchase_return.created_at,
                credit_total=credit_total,
                return_credit_remaining=return_credit_remaining,
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
    ) -> list[PurchaseReturnHistoryResponse]:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Purchase transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.PURCHASE:
                raise ConflictError("Return history is only available for purchases.")
            returns = await self.purchase_return_repository.list_by_transaction(
                transaction_id
            )
            transaction_items = {item.id: item for item in transaction.items}
            responses = []
            for purchase_return in returns:
                response_items = []
                for return_item in purchase_return.items:
                    transaction_item = transaction_items[return_item.transaction_item_id]
                    product = await self.product_repository.get_by_id(
                        farm_id,
                        transaction_item.product_id,
                    )
                    if product is None:
                        raise ResourceNotFoundError("Purchase product not found.")
                    linked_batch = (
                        await self.chicken_transaction_item_repository.get_by_transaction_item(
                            transaction_item.id
                        )
                    )
                    response_items.append(
                        PurchaseReturnItemResponse(
                            id=return_item.id,
                            transaction_item_id=transaction_item.id,
                            product_id=product.id,
                            product_name=getattr(product, "name", None),
                            batch_id=(
                                linked_batch.batch_id
                                if linked_batch is not None
                                else None
                            ),
                            chicken_type=(
                                linked_batch.batch.chicken_type
                                if linked_batch is not None
                                else None
                            ),
                            quantity_returned=return_item.quantity,
                            credit_amount=return_item.credit_amount,
                            block_allocations=[
                                BlockAllocationResponse(
                                    block_id=allocation.block_id,
                                    quantity=allocation.quantity,
                                )
                                for allocation in return_item.block_allocations
                            ],
                        )
                    )
                responses.append(
                    PurchaseReturnHistoryResponse(
                        id=purchase_return.id,
                        transaction_id=transaction_id,
                        return_date=purchase_return.return_date,
                        return_time=purchase_return.return_time,
                        reason=purchase_return.reason,
                        notes=purchase_return.notes,
                        created_at=purchase_return.created_at,
                        credit_total=sum(
                            (item.credit_amount for item in response_items),
                            Decimal("0.00"),
                        ),
                        items=response_items,
                    )
                )
            return responses

    async def _purchase_balances(self, transaction):
        transaction_id = transaction.id
        payments = await self.payment_repository.list_by_transaction(transaction_id)
        amount_paid = sum(
            (payment.amount for payment in payments),
            Decimal("0.00"),
        )
        supplier_refunds = await self.supplier_refund_repository.get_total_by_transaction(
            transaction_id
        )
        return_credit = await self.purchase_return_repository.get_total_credit_by_transaction(
            transaction_id
        )
        replacement_credit = (
            await self.replacement_repository.get_total_credit_applied_by_transaction(
                transaction_id
            )
        )
        purchase_total = sum(
            (item.total_amount for item in transaction.items),
            Decimal("0.00"),
        )
        return calculate_transaction_balance(
            purchase_total,
            amount_paid,
            supplier_refunds,
            return_credit,
            settlement_adjustment=(
                get_settlement_adjustment(transaction) - replacement_credit
            ),
        )

    async def _return_credit_remaining(
        self,
        transaction_id: UUID,
        available_credit: Decimal,
    ) -> Decimal:
        total_credit = await self.purchase_return_repository.get_total_credit_by_transaction(
            transaction_id
        )
        supplier_refunds = await self.supplier_refund_repository.get_total_by_transaction(
            transaction_id
        )
        replacement_credit = (
            await self.replacement_repository.get_total_credit_applied_by_transaction(
                transaction_id
            )
        )
        unspent_return_credit = max(
            total_credit - supplier_refunds - replacement_credit,
            Decimal("0.00"),
        )
        return min(unspent_return_credit, available_credit)

    @staticmethod
    def _base_quantity(transaction_item) -> Decimal:
        return (
            Decimal(str(transaction_item.quantity))
            * Decimal(str(transaction_item.conversion_factor))
        )
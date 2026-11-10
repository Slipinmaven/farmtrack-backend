from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.purchase_replacement_repository import PurchaseReplacementRepository
from app.repositories.purchase_return_repository import PurchaseReturnRepository
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
    TransactionStatus,
    TransactionType,
)
from app.schemas.purchase_replacement import (
    PurchaseReplacementCreateRequest,
    PurchaseReplacementHistoryResponse,
    PurchaseReplacementItemResponse,
    PurchaseReplacementResponse,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService
from app.services.transaction_balance import (
    calculate_transaction_balance,
    get_settlement_adjustment,
)

logger = get_application_logger()


class PurchaseReplacementService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        chicken_batch_repository: ChickenBatchRepository,
        block_repository: BlockRepository,
        batch_block_repository: BatchBlockRepository,
        purchase_return_repository: PurchaseReturnRepository,
        purchase_supplier_refund_repository: PurchaseSupplierRefundRepository,
        purchase_replacement_repository: PurchaseReplacementRepository,
        transaction_payment_repository: TransactionPaymentRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        inventory_service: InventoryService | None = None,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository
        self.purchase_return_repository = purchase_return_repository
        self.purchase_supplier_refund_repository = purchase_supplier_refund_repository
        self.purchase_replacement_repository = purchase_replacement_repository
        self.transaction_payment_repository = transaction_payment_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.inventory_service = inventory_service

    async def create_replacement(
        self,
        farm_id: UUID,
        transaction_id: UUID,
        request: PurchaseReplacementCreateRequest,
        user_id: UUID | None = None,
    ) -> PurchaseReplacementResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Purchase transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.PURCHASE:
                raise ConflictError("Replacement chickens can only settle purchase returns.")
            if transaction.status == TransactionStatus.CANCELLED:
                raise ConflictError("A cancelled purchase cannot receive replacement chickens.")

            return_headers = await self.purchase_return_repository.list_by_transaction(
                transaction_id
            )
            purchase_return = next(
                (record for record in return_headers if record.id == request.purchase_return_id),
                None,
            )
            if purchase_return is None:
                raise ResourceNotFoundError(
                    "Purchase return was not found on this transaction."
                )

            requested_credit = sum(
                (item.credit_applied_amount for item in request.items),
                Decimal("0.00"),
            )
            current_balances = await self._purchase_balances(transaction)
            if requested_credit > current_balances.credit_balance:
                raise ConflictError(
                    f"Replacement credit exceeds the transaction's available credit of "
                    f"{current_balances.credit_balance}."
                )

            plans = []
            stock_increments: defaultdict[tuple[UUID, UUID], int] = defaultdict(int)
            block_increments: defaultdict[UUID, int] = defaultdict(int)
            batches = {}
            blocks = {}
            transaction_items = {item.id: item for item in transaction.items}
            for replacement_item in request.items:
                return_item = await self.purchase_return_repository.get_return_item(
                    transaction_id,
                    replacement_item.purchase_return_item_id,
                )
                if (
                    return_item is None
                    or return_item.purchase_return_id != purchase_return.id
                ):
                    raise ResourceNotFoundError(
                        "Purchase return item was not found on the selected return."
                    )
                source_transaction_item = transaction_items.get(
                    return_item.transaction_item_id
                )
                if source_transaction_item is None:
                    raise ResourceNotFoundError(
                        "The purchase item for this replacement no longer exists."
                    )

                refunded = (
                    await self.purchase_supplier_refund_repository.get_total_by_return_item(
                        return_item.id
                    )
                )
                previously_replaced = (
                    await self.purchase_replacement_repository.get_credit_applied_by_return_item(
                        return_item.id
                    )
                )
                available_credit = max(
                    return_item.credit_amount - refunded - previously_replaced,
                    Decimal("0.00"),
                )
                if replacement_item.credit_applied_amount > available_credit:
                    raise ConflictError(
                        f"Replacement credit exceeds the unsettled return credit of "
                        f"{available_credit}."
                    )

                batch = batches.get(replacement_item.batch_id)
                if batch is None:
                    batch = await self.chicken_batch_repository.get_by_id(
                        farm_id,
                        replacement_item.batch_id,
                    )
                    if batch is None:
                        raise ResourceNotFoundError("Replacement chicken batch not found.")
                    batches[batch.id] = batch
                if batch.status != ChickenBatchStatus.ACTIVE:
                    raise ConflictError("Replacement chickens must enter an active batch.")
                if batch.product_id not in (None, source_transaction_item.product_id):
                    raise ConflictError(
                        f"Batch '{batch.name}' is not linked to the selected chicken product."
                    )
                if batch.product_id is None:
                    batch.product_id = source_transaction_item.product_id

                allocation_plans = []
                for allocation in replacement_item.block_allocations:
                    block = blocks.get(allocation.block_id)
                    if block is None:
                        block = await self.block_repository.get_by_id_for_update(
                            farm_id,
                            allocation.block_id,
                        )
                        if block is None:
                            raise ResourceNotFoundError(
                                "Replacement block not found for this farm."
                            )
                        if not block.is_active:
                            raise ConflictError(
                                "Replacement chickens must enter an active block."
                            )
                        blocks[block.id] = block

                    stock_increments[(batch.id, block.id)] += allocation.quantity
                    block_increments[block.id] += allocation.quantity
                    allocation_plans.append(allocation)

                plans.append(
                    (replacement_item, return_item, batch, allocation_plans)
                )

            for block_id, additional_quantity in block_increments.items():
                block = blocks[block_id]
                current_quantity = await self.batch_block_repository.get_total_quantity_by_block(
                    block_id
                )
                max_quantity = block.capacity + block.over_capacity_limit
                if current_quantity + additional_quantity > max_quantity:
                    raise ConflictError(
                        f"Replacement chickens would exceed block '{block.name}' capacity."
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

            replacement = await self.purchase_replacement_repository.create_replacement(
                {
                    "transaction_id": transaction_id,
                    "purchase_return_id": purchase_return.id,
                    "replacement_date": request.replacement_date,
                    "replacement_time": request.replacement_time,
                    "notes": request.notes,
                }
            )
            response_items = []
            activity_items: list[dict[str, object]] = []
            for replacement_item, return_item, batch, allocations in plans:
                saved_item = await self.purchase_replacement_repository.create_item(
                    {
                        "purchase_replacement_id": replacement.id,
                        "purchase_return_item_id": return_item.id,
                        "batch_id": batch.id,
                        "quantity_received": replacement_item.quantity_received,
                        "bonus_quantity": replacement_item.bonus_quantity,
                        "credit_applied_amount": replacement_item.credit_applied_amount,
                    }
                )
                if self.inventory_service is not None:
                    source_transaction_item = transaction_items.get(
                        return_item.transaction_item_id
                    )
                    if source_transaction_item is None:
                        raise ResourceNotFoundError(
                            "The purchase item for this replacement no longer exists."
                        )
                    await self.inventory_service.append_movement(
                        farm_id=farm_id,
                        user_id=user_id,
                        product_id=source_transaction_item.product_id,
                        quantity_delta=Decimal(saved_item.quantity_received),
                        movement_type=InventoryMovementType.RECEIPT,
                        occurred_on=request.replacement_date,
                        notes=replacement.notes or "Supplier chicken replacement",
                        source_type="purchase_replacement",
                        source_id=replacement.id,
                        source_item_id=saved_item.id,
                        unit_cost=(
                            source_transaction_item.total_amount
                            / (
                                source_transaction_item.quantity
                                * source_transaction_item.conversion_factor
                            )
                            if source_transaction_item.quantity
                            and source_transaction_item.conversion_factor
                            else None
                        ),
                    )
                block_responses = []
                for allocation in allocations:
                    await self.purchase_replacement_repository.create_allocation(
                        {
                            "purchase_replacement_item_id": saved_item.id,
                            "block_id": allocation.block_id,
                            "quantity": allocation.quantity,
                        }
                    )
                    block_responses.append(
                        BlockAllocationResponse(
                            block_id=allocation.block_id,
                            quantity=allocation.quantity,
                        )
                    )
                response_items.append(
                    PurchaseReplacementItemResponse(
                        id=saved_item.id,
                        purchase_return_item_id=return_item.id,
                        batch_id=batch.id,
                        chicken_type=batch.chicken_type,
                        quantity_received=Decimal(saved_item.quantity_received),
                        replacement_quantity=Decimal(
                            saved_item.quantity_received - saved_item.bonus_quantity
                        ),
                        bonus_quantity=Decimal(saved_item.bonus_quantity),
                        credit_applied_amount=saved_item.credit_applied_amount,
                        block_allocations=block_responses,
                    )
                )
                activity_items.append(
                    {
                        "batch_name": batch.name,
                        "quantity_received": str(saved_item.quantity_received),
                        "replacement_quantity": str(
                            saved_item.quantity_received - saved_item.bonus_quantity
                        ),
                        "bonus_quantity": str(saved_item.bonus_quantity),
                        "credit_applied_amount": str(saved_item.credit_applied_amount),
                        "chicken_type": (
                            batch.chicken_type.value
                            if batch.chicken_type is not None
                            else None
                        ),
                        "block_allocations": [
                            {
                                "quantity": str(allocation.quantity),
                                "block_name": blocks[allocation.block_id].name,
                            }
                            for allocation in allocations
                        ],
                    }
                )

            for key, quantity in stock_increments.items():
                batch_block = stock_rows[key]
                if batch_block is None:
                    await self.batch_block_repository.create(
                        {"batch_id": key[0], "block_id": key[1], "quantity": quantity}
                    )
                else:
                    batch_block.quantity += quantity
                    await self.batch_block_repository.update(batch_block)

            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.PURCHASE_REPLACEMENT_RECEIVED,
                entity_type=ActivityEntityType.PURCHASE_REPLACEMENT,
                entity_id=replacement.id,
                details={
                    "transaction_id": str(transaction_id),
                    "transaction_type": transaction.transaction_type.value,
                    "reference_number": transaction.reference_number,
                    "purchase_return_id": str(purchase_return.id),
                    "replacement_date": request.replacement_date.isoformat(),
                    "item_count": len(response_items),
                    "quantity_received": str(
                        sum(item.quantity_received for item in response_items)
                    ),
                    "bonus_quantity": str(
                        sum(item.bonus_quantity for item in response_items)
                    ),
                    "items": activity_items,
                },
            )
            await self.unit_of_work.flush()
            balances = await self._purchase_balances(transaction)
            return_credit_remaining = await self._return_credit_remaining(
                transaction_id,
                balances.credit_balance,
            )
            await self.unit_of_work.commit()
            credit_applied_total = sum(
                (item.credit_applied_amount for item in response_items),
                Decimal("0.00"),
            )
            logger.info(
                "purchase_replacement_received",
                extra={
                    "event": "purchase_replacement_received",
                    "farm_id": farm_id,
                    "user_id": user_id,
                    "transaction_id": transaction_id,
                    "replacement_id": replacement.id,
                    "credit_applied_total": str(credit_applied_total),
                },
            )
            return PurchaseReplacementResponse(
                id=replacement.id,
                purchase_return_id=purchase_return.id,
                transaction_id=transaction_id,
                replacement_date=replacement.replacement_date,
                replacement_time=replacement.replacement_time,
                notes=replacement.notes,
                created_at=replacement.created_at,
                credit_applied_total=credit_applied_total,
                return_credit_remaining=return_credit_remaining,
                adjusted_transaction_total=balances.adjusted_transaction_total,
                amount_paid=balances.amount_paid,
                balance_due=balances.balance_due,
                credit_balance=balances.credit_balance,
                items=response_items,
            )

    async def list_replacements(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[PurchaseReplacementHistoryResponse]:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Purchase transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.PURCHASE:
                raise ConflictError("Replacement history is only available for purchases.")
            replacements = await self.purchase_replacement_repository.list_by_transaction(
                transaction_id
            )
            responses = []
            for replacement in replacements:
                items = [
                    PurchaseReplacementItemResponse(
                        id=item.id,
                        purchase_return_item_id=item.purchase_return_item_id,
                        batch_id=item.batch_id,
                        chicken_type=item.batch.chicken_type,
                        quantity_received=Decimal(item.quantity_received),
                        replacement_quantity=Decimal(
                            item.quantity_received - item.bonus_quantity
                        ),
                        bonus_quantity=Decimal(item.bonus_quantity),
                        credit_applied_amount=item.credit_applied_amount,
                        block_allocations=[
                            BlockAllocationResponse(
                                block_id=allocation.block_id,
                                quantity=allocation.quantity,
                            )
                            for allocation in item.block_allocations
                        ],
                    )
                    for item in replacement.items
                ]
                responses.append(
                    PurchaseReplacementHistoryResponse(
                        id=replacement.id,
                        purchase_return_id=replacement.purchase_return_id,
                        transaction_id=replacement.transaction_id,
                        replacement_date=replacement.replacement_date,
                        replacement_time=replacement.replacement_time,
                        notes=replacement.notes,
                        created_at=replacement.created_at,
                        credit_applied_total=sum(
                            (item.credit_applied_amount for item in items),
                            Decimal("0.00"),
                        ),
                        items=items,
                    )
                )
            return responses

    async def _purchase_balances(self, transaction):
        payments = await self.transaction_payment_repository.list_by_transaction(
            transaction.id
        )
        amount_received = sum(
            (payment.amount for payment in payments),
            Decimal("0.00"),
        )
        refunds = await self.purchase_supplier_refund_repository.get_total_by_transaction(
            transaction.id
        )
        return_credits = (
            await self.purchase_return_repository.get_total_credit_by_transaction(
                transaction.id
            )
        )
        replacement_credits = (
            await self.purchase_replacement_repository.get_total_credit_applied_by_transaction(
                transaction.id
            )
        )
        transaction_total = sum(
            (item.total_amount for item in transaction.items),
            Decimal("0.00"),
        )
        return calculate_transaction_balance(
            transaction_total,
            amount_received,
            refunds,
            return_credits,
            settlement_adjustment=(
                get_settlement_adjustment(transaction) - replacement_credits
            ),
        )

    async def _return_credit_remaining(
        self,
        transaction_id: UUID,
        available_credit: Decimal,
    ) -> Decimal:
        credit = await self.purchase_return_repository.get_total_credit_by_transaction(
            transaction_id
        )
        refunds = await self.purchase_supplier_refund_repository.get_total_by_transaction(
            transaction_id
        )
        replacements = (
            await self.purchase_replacement_repository.get_total_credit_applied_by_transaction(
                transaction_id
            )
        )
        unspent_return_credit = max(
            credit - refunds - replacements,
            Decimal("0.00"),
        )
        return min(unspent_return_credit, available_credit)
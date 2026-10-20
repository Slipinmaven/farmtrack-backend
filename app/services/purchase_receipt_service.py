from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.database_errors import integrity_constraint_name
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.services.activity_service import ActivityService
from app.services.chicken_age import calculate_hatch_date as _calculate_hatch_date
from app.services.inventory_service import InventoryService
from app.models.blocks import Block
from app.models.chicken_transaction_items import ChickenTransactionItem
from app.models.chicken_batches import ChickenBatch
from app.models.transaction_items import TransactionItem
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.chicken_batch_name_counter_repository import (
    ChickenBatchNameCounterRepository,
)
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.chicken_transaction_item_repository import (
    ChickenTransactionItemRepository,
)
from app.repositories.farm_repository import FarmRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.purchase_receipt_item_repository import (
    PurchaseReceiptItemRepository,
)
from app.repositories.purchase_receipt_item_block_allocation_repository import (
    PurchaseReceiptItemBlockAllocationRepository,
)
from app.repositories.purchase_receipt_repository import PurchaseReceiptRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.chicken_purchase import (
    BlockAllocationResponse,
    ChickenReceiptItemRequest,
    CreateBatchAssignment,
    ExistingBatchAssignment,
    PurchaseReceiptCreateRequest,
    PurchaseReceiptItemResponse,
    PurchaseReceiptResponse,
)
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    InventoryMovementType,
    ProductType,
    TransactionStatus,
    TransactionType,
)

app_logger = get_application_logger()


class PurchaseReceiptService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        product_repository: ProductRepository,
        receipt_repository: PurchaseReceiptRepository,
        receipt_item_repository: PurchaseReceiptItemRepository,
        receipt_item_block_allocation_repository: PurchaseReceiptItemBlockAllocationRepository,
        chicken_batch_repository: ChickenBatchRepository,
        chicken_transaction_item_repository: ChickenTransactionItemRepository,
        block_repository: BlockRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        chicken_batch_name_counter_repository: ChickenBatchNameCounterRepository | None = None,
        inventory_service: InventoryService | None = None,
        farm_repository: FarmRepository | None = None,
    ):
        self.transaction_repository = transaction_repository
        self.product_repository = product_repository
        self.receipt_repository = receipt_repository
        self.receipt_item_repository = receipt_item_repository
        self.receipt_item_block_allocation_repository = (
            receipt_item_block_allocation_repository
        )
        self.chicken_batch_repository = chicken_batch_repository
        self.chicken_transaction_item_repository = chicken_transaction_item_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.chicken_batch_name_counter_repository = (
            chicken_batch_name_counter_repository
        )
        self.inventory_service = inventory_service
        self.farm_repository = farm_repository

    async def list_receipts(self, farm_id: UUID) -> list[PurchaseReceiptResponse]:
        async with self.unit_of_work:
            receipts = await self.receipt_repository.list_by_farm(farm_id)
            return [await self._to_response(receipt) for receipt in receipts]

    async def get_receipt(
        self,
        farm_id: UUID,
        receipt_id: UUID,
    ) -> PurchaseReceiptResponse:
        async with self.unit_of_work:
            receipt = await self.receipt_repository.get_by_id_for_farm(
                farm_id,
                receipt_id,
            )
            if receipt is None:
                raise ResourceNotFoundError("Purchase receipt not found.")
            return await self._to_response(receipt)

    async def create_receipt(
        self,
        farm_id: UUID,
        receipt_data: PurchaseReceiptCreateRequest,
        user_id: UUID | None = None,
    ) -> PurchaseReceiptResponse:
        try:
            async with self.unit_of_work:
                if self.farm_repository is not None:
                    farm = await self.farm_repository.get_by_id_for_update(farm_id)
                    if farm is None:
                        raise ResourceNotFoundError("Farm not found.")
                transaction = await self.transaction_repository.get_by_id_for_update(
                    farm_id,
                    receipt_data.transaction_id,
                )
                if transaction is None:
                    raise ResourceNotFoundError("Purchase transaction not found.")
                if transaction.transaction_type != TransactionType.PURCHASE:
                    raise ConflictError("Receipts can only be recorded for purchases.")
                if transaction.status == TransactionStatus.CANCELLED:
                    raise ConflictError("A cancelled purchase cannot receive deliveries.")

                transaction_items = {item.id: item for item in transaction.items}
                previously_received = (
                    await self.receipt_item_repository.get_received_quantities_by_transaction(
                        transaction.id
                    )
                )
                resolved_items: list[
                    tuple[
                        ChickenReceiptItemRequest,
                        TransactionItem,
                        ChickenTransactionItem | None,
                        ChickenBatch | None,
                        Decimal,
                    ]
                ] = []
                blocks: dict[UUID, Block] = {}
                planned_block_quantities: defaultdict[UUID, int] = defaultdict(int)

                for item_request in receipt_data.items:
                    transaction_item = transaction_items.get(
                        item_request.transaction_item_id
                    )
                    if transaction_item is None:
                        raise ResourceNotFoundError(
                            "A transaction item was not found on this purchase."
                        )

                    product = await self.product_repository.get_by_id(
                        farm_id,
                        transaction_item.product_id,
                    )
                    if product is None:
                        raise ResourceNotFoundError("Product not found.")
                    if product.product_type != ProductType.CHICKENS:
                        raise ConflictError(
                            "Chicken receipts can only be recorded for chicken products."
                        )

                    ordered_quantity = (
                        transaction_item.quantity * transaction_item.conversion_factor
                    )
                    if (
                        ordered_quantity <= 0
                        or ordered_quantity != ordered_quantity.to_integral_value()
                    ):
                        raise ConflictError(
                            "The purchase item does not represent a whole number of chickens."
                        )

                    prior_quantity = previously_received.get(
                        transaction_item.id,
                        Decimal("0"),
                    )
                    remaining_quantity = ordered_quantity - prior_quantity
                    received_quantity = Decimal(item_request.quantity_received)
                    if received_quantity > remaining_quantity:
                        raise ConflictError(
                            f"Received quantity exceeds the remaining quantity of "
                            f"{remaining_quantity} chickens for this purchase item."
                        )

                    chicken_transaction_item = (
                        await self.chicken_transaction_item_repository.get_by_transaction_item(
                            transaction_item.id
                        )
                    )
                    batch = await self._get_batch_for_assignment(
                        farm_id,
                        item_request,
                        chicken_transaction_item,
                    )
                    if batch is None:
                        assignment = item_request.batch_assignment
                        assert isinstance(assignment, CreateBatchAssignment)
                        assigned_chicken_type = assignment.new_batch.chicken_type
                    else:
                        assigned_chicken_type = batch.chicken_type

                    if transaction_item.chicken_type is None:
                        transaction_item.chicken_type = assigned_chicken_type
                        await self.unit_of_work.flush()
                    elif transaction_item.chicken_type != assigned_chicken_type:
                        raise ConflictError(
                            "The assigned batch chicken type does not match the purchase item."
                        )

                    resolved_items.append(
                        (
                            item_request,
                            transaction_item,
                            chicken_transaction_item,
                            batch,
                            remaining_quantity - received_quantity,
                        )
                    )
                    for allocation in item_request.block_allocations:
                        planned_block_quantities[allocation.block_id] += allocation.quantity

                for block_id in sorted(planned_block_quantities, key=str):
                    block = await self.block_repository.get_by_id_for_update(
                        farm_id,
                        block_id,
                    )
                    if block is None:
                        raise ResourceNotFoundError("Block not found for this farm.")
                    if not block.is_active:
                        raise ConflictError("Chickens cannot be allocated to an inactive block.")
                    blocks[block_id] = block
                    current_quantity = (
                        await self.batch_block_repository.get_total_quantity_by_block(
                            block_id
                        )
                    )
                    maximum_quantity = block.capacity + block.over_capacity_limit
                    if current_quantity + planned_block_quantities[block_id] > maximum_quantity:
                        raise ConflictError(
                            f"Allocating this delivery would exceed the capacity limit "
                            f"for block '{block.name}'."
                        )

                receipt = await self.receipt_repository.create(
                    {
                        "transaction_id": transaction.id,
                        "received_date": receipt_data.received_date,
                        "received_time": receipt_data.received_time,
                        "notes": receipt_data.notes,
                    }
                )
                response_items: list[PurchaseReceiptItemResponse] = []

                for (
                    item_request,
                    transaction_item,
                    chicken_transaction_item,
                    batch,
                    remaining_after_receipt,
                ) in resolved_items:
                    if batch is None:
                        assignment = item_request.batch_assignment
                        assert isinstance(assignment, CreateBatchAssignment)
                        try:
                            hatch_date = _calculate_hatch_date(
                                receipt_data.received_date,
                                assignment.new_batch.age,
                                assignment.new_batch.age_unit,
                            )
                        except (OverflowError, ValueError) as exc:
                            raise ConflictError(
                                "Chicken age is outside the valid receipt-date range."
                            ) from exc
                        batch_name = assignment.new_batch.name
                        if batch_name is None:
                            if self.chicken_batch_name_counter_repository is None:
                                raise RuntimeError(
                                    "Chicken batch name generation is not configured."
                                )
                            batch_number = (
                                await self.chicken_batch_name_counter_repository.allocate_next_number(
                                    farm_id,
                                    receipt_data.received_date,
                                )
                            )
                            batch_name = (
                                f"{receipt_data.received_date.year} "
                                f"{receipt_data.received_date.strftime('%B')} "
                                f"{receipt_data.received_date.day} Batch {batch_number}"
                            )
                        batch_data = assignment.new_batch.model_dump(
                            exclude={"age", "age_unit", "name"}
                        )
                        batch = await self.chicken_batch_repository.create(
                            farm_id,
                            {
                                **batch_data,
                                "name": batch_name,
                                "hatch_date": hatch_date,
                            },
                        )

                    if chicken_transaction_item is None:
                        chicken_transaction_item = (
                            await self.chicken_transaction_item_repository.create(
                                {
                                    "transaction_item_id": transaction_item.id,
                                    "batch_id": batch.id,
                                    "block_id": None,
                                }
                            )
                        )

                    receipt_item = await self.receipt_item_repository.create(
                        {
                            "purchase_receipt_id": receipt.id,
                            "transaction_item_id": item_request.transaction_item_id,
                            "quantity": Decimal(item_request.quantity_received),
                        }
                    )
                    if self.inventory_service is not None:
                        await self.inventory_service.append_movement(
                            farm_id=farm_id,
                            user_id=user_id,
                            product_id=transaction_item.product_id,
                            quantity_delta=Decimal(receipt_item.quantity),
                            movement_type=InventoryMovementType.RECEIPT,
                            occurred_on=receipt_data.received_date,
                            notes=receipt.notes or "Chicken purchase receipt",
                            source_type="purchase_receipt",
                            source_id=receipt.id,
                            source_item_id=receipt_item.id,
                            unit_cost=(
                                transaction_item.total_amount
                                / (
                                    transaction_item.quantity
                                    * transaction_item.conversion_factor
                                )
                                if transaction_item.quantity
                                and transaction_item.conversion_factor
                                else None
                            ),
                        )
                    response_items.append(
                        PurchaseReceiptItemResponse(
                            id=receipt_item.id,
                            transaction_item_id=receipt_item.transaction_item_id,
                            quantity_received=receipt_item.quantity,
                            batch_id=batch.id,
                            batch_name=getattr(batch, "name", None),
                            hatch_date=batch.hatch_date,
                            remaining_quantity=remaining_after_receipt,
                            block_allocations=[
                                BlockAllocationResponse(
                                    block_id=allocation.block_id,
                                    quantity=allocation.quantity,
                                    block_name=getattr(
                                        getattr(allocation, "block", None),
                                        "name",
                                        None,
                                    ),
                                )
                                for allocation in item_request.block_allocations
                            ],
                        )
                    )
                    for allocation in item_request.block_allocations:
                        await self.receipt_item_block_allocation_repository.create(
                            {
                                "purchase_receipt_item_id": receipt_item.id,
                                "block_id": allocation.block_id,
                                "quantity": allocation.quantity,
                            }
                        )

                    for allocation in item_request.block_allocations:
                        batch_block = await self.batch_block_repository.get_by_batch_and_block(
                            batch.id,
                            allocation.block_id,
                        )
                        if batch_block is None:
                            await self.batch_block_repository.create(
                                {
                                    "batch_id": batch.id,
                                    "block_id": allocation.block_id,
                                    "quantity": allocation.quantity,
                                }
                            )
                        else:
                            batch_block.quantity += allocation.quantity
                            await self.batch_block_repository.update(batch_block)

                contact_id = getattr(transaction, "contact_id", None)
                await self.activity_service.record(
                    farm_id=farm_id,
                    user_id=user_id,
                    activity_type=ActivityType.PURCHASE_RECEIPT_CREATED,
                    entity_type=ActivityEntityType.PURCHASE_RECEIPT,
                    entity_id=receipt.id,
                    details={
                        "transaction_id": str(transaction.id),
                        "transaction_type": transaction.transaction_type.value,
                        "reference_number": getattr(
                            transaction,
                            "reference_number",
                            None,
                        ),
                        "contact_id": str(contact_id) if contact_id is not None else None,
                        "received_date": receipt_data.received_date.isoformat(),
                        "notes": receipt.notes,
                        "item_count": len(response_items),
                        "quantity_received": str(
                            sum(item.quantity_received for item in response_items)
                        ),
                        "items": [
                            {
                                "batch_name": item.batch_name,
                                "quantity_received": str(item.quantity_received),
                                "allocations": [
                                    {
                                        "quantity": str(allocation.quantity),
                                        "block_name": allocation.block_name,
                                    }
                                    for allocation in item.block_allocations
                                ],
                            }
                            for item in response_items
                        ],
                    },
                )
                await self.unit_of_work.commit()
                app_logger.info(
                    "purchase_receipt_created",
                    extra={
                        "event": "purchase_receipt_created",
                        "farm_id": farm_id,
                        "user_id": user_id,
                        "transaction_id": transaction.id,
                        "receipt_id": receipt.id,
                        "item_count": len(response_items),
                    },
                )
                return PurchaseReceiptResponse(
                    id=receipt.id,
                    transaction_id=receipt.transaction_id,
                    received_date=receipt.received_date,
                    received_time=receipt.received_time,
                    notes=receipt.notes,
                    created_at=receipt.created_at,
                    items=response_items,
                )
        except IntegrityError as exc:
            if integrity_constraint_name(exc) == "uq_chicken_batches_farm_id_name":
                raise ConflictError(
                    "A chicken batch with this name already exists for this farm."
                ) from exc
            raise

    async def _get_batch_for_assignment(
        self,
        farm_id: UUID,
        item_request: ChickenReceiptItemRequest,
        chicken_transaction_item: ChickenTransactionItem | None,
    ) -> ChickenBatch | None:
        assignment = item_request.batch_assignment
        if chicken_transaction_item is not None:
            if assignment is not None and (
                not isinstance(assignment, ExistingBatchAssignment)
                or assignment.batch_id != chicken_transaction_item.batch_id
            ):
                raise ConflictError(
                    "This purchase item is already linked to a different chicken batch."
                )
            batch = await self.chicken_batch_repository.get_by_id(
                farm_id,
                chicken_transaction_item.batch_id,
            )
            if batch is None:
                raise ResourceNotFoundError("Linked chicken batch not found.")
            if batch.status != ChickenBatchStatus.ACTIVE:
                raise ConflictError("Chickens cannot be received into an inactive batch.")
            return batch

        if assignment is None:
            raise ConflictError(
                "A batch assignment is required until this purchase item is linked to a batch."
            )
        if isinstance(assignment, CreateBatchAssignment):
            return None

        batch = await self.chicken_batch_repository.get_by_id(
            farm_id,
            assignment.batch_id,
        )
        if batch is None:
            raise ResourceNotFoundError("Chicken batch not found.")
        if batch.status != ChickenBatchStatus.ACTIVE:
            raise ConflictError("Chickens cannot be received into an inactive batch.")
        return batch

    async def _to_response(self, receipt) -> PurchaseReceiptResponse:
        received_quantities = (
            await self.receipt_item_repository.get_received_quantities_by_transaction(
                receipt.transaction_id
            )
        )
        response_items = []
        for receipt_item in receipt.items:
            transaction_item = receipt_item.transaction_item
            batch_link = transaction_item.chicken_transaction_item
            batch = batch_link.batch if batch_link is not None else None
            ordered_quantity = (
                transaction_item.quantity * transaction_item.conversion_factor
            )
            response_items.append(
                PurchaseReceiptItemResponse(
                    id=receipt_item.id,
                    transaction_item_id=transaction_item.id,
                    quantity_received=receipt_item.quantity,
                    batch_id=batch.id if batch is not None else None,
                    batch_name=getattr(batch, "name", None) if batch is not None else None,
                    hatch_date=batch.hatch_date if batch is not None else None,
                    remaining_quantity=(
                        ordered_quantity
                        - received_quantities.get(transaction_item.id, Decimal("0"))
                    ),
                    block_allocations=[
                        BlockAllocationResponse(
                            block_id=allocation.block_id,
                            quantity=allocation.quantity,
                        )
                        for allocation in receipt_item.block_allocations
                    ],
                )
            )
        return PurchaseReceiptResponse(
            id=receipt.id,
            transaction_id=receipt.transaction_id,
            received_date=receipt.received_date,
            received_time=receipt.received_time,
            notes=receipt.notes,
            created_at=receipt.created_at,
            items=response_items,
        )
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.repositories.sale_delivery_repository import SaleDeliveryRepository
from app.repositories.sale_return_repository import SaleReturnRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    InventoryMovementType,
    ProductType,
    SaleReturnType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.sale_delivery import (
    SaleDeliveryAllocationResponse,
    SaleDeliveryCreateRequest,
    SaleDeliveryItemResponse,
    SaleDeliveryResponse,
    SaleFulfillmentItemResponse,
    SaleFulfillmentResponse,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService

logger = get_application_logger()


class SaleDeliveryService:
    def __init__(
        self,
        transaction_repository,
        product_repository,
        batch_repository,
        block_repository,
        batch_block_repository,
        sale_delivery_repository: SaleDeliveryRepository,
        sale_return_repository: SaleReturnRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        inventory_service: InventoryService | None = None,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.product_repository = product_repository
        self.batch_repository = batch_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository
        self.sale_delivery_repository = sale_delivery_repository
        self.sale_return_repository = sale_return_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.inventory_service = inventory_service

    async def create_delivery(
        self,
        farm_id: UUID,
        transaction_id: UUID,
        request: SaleDeliveryCreateRequest,
        user_id: UUID | None = None,
        *,
        commit: bool = True,
    ) -> SaleDeliveryResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError(
                    f"Sale transaction '{transaction_id}' was not found."
                )
            self._validate_sale_transaction(transaction)

            transaction_items = {item.id: item for item in transaction.items}
            previously_delivered = (
                await self.sale_delivery_repository.get_delivered_quantities_by_transaction(
                    transaction_id
                )
            )
            cancelled_quantities = (
                await self.sale_return_repository.get_quantities_by_type(
                    transaction_id,
                    SaleReturnType.UNDELIVERED_CANCELLED.value,
                )
            )
            planned_items = []
            planned_stock: defaultdict[tuple[UUID, UUID], int] = defaultdict(int)

            for delivery_item in request.items:
                transaction_item = transaction_items.get(
                    delivery_item.transaction_item_id
                )
                if transaction_item is None:
                    raise ResourceNotFoundError(
                        f"Transaction item '{delivery_item.transaction_item_id}' was not found on sale '{transaction_id}'."
                    )

                product = await self.product_repository.get_by_id(
                    farm_id,
                    transaction_item.product_id,
                )
                if product is None:
                    raise ResourceNotFoundError(
                        f"Product '{transaction_item.product_id}' does not exist."
                    )
                if product.product_type != ProductType.CHICKENS:
                    raise ConflictError(
                        "Only chicken sales can be delivered through this flow."
                    )

                ordered_quantity = self._ordered_quantity(transaction_item)
                already_delivered = previously_delivered.get(
                    transaction_item.id,
                    Decimal("0"),
                )
                remaining_quantity = (
                    ordered_quantity
                    - already_delivered
                    - cancelled_quantities.get(transaction_item.id, Decimal("0"))
                )
                requested_quantity = Decimal(delivery_item.quantity_delivered)
                if requested_quantity > remaining_quantity:
                    raise ConflictError(
                        f"Delivery quantity exceeds the outstanding quantity of "
                        f"{remaining_quantity} chickens for this sale item."
                    )

                resolved_allocations = []
                for allocation in sorted(
                    delivery_item.batch_allocations,
                    key=lambda item: (str(item.batch_id), str(item.block_id)),
                ):
                    batch = await self.batch_repository.get_by_id(
                        farm_id,
                        allocation.batch_id,
                    )
                    if batch is None:
                        raise ResourceNotFoundError(
                            f"Batch '{allocation.batch_id}' was not found."
                        )
                    if batch.status != ChickenBatchStatus.ACTIVE:
                        raise ConflictError(
                            "Chickens cannot be delivered from an inactive batch."
                        )
                    if (
                        transaction_item.chicken_type is not None
                        and batch.chicken_type != transaction_item.chicken_type
                    ):
                        raise ConflictError(
                            "Selected batch chicken type does not match the sale item."
                        )

                    block = await self.block_repository.get_by_id_for_update(
                        farm_id,
                        allocation.block_id,
                    )
                    if block is None:
                        raise ResourceNotFoundError(
                            f"Block '{allocation.block_id}' was not found."
                        )
                    if not block.is_active:
                        raise ConflictError(
                            "Chickens cannot be delivered from an inactive block."
                        )

                    batch_block = await self.batch_block_repository.get_by_batch_and_block(
                        allocation.batch_id,
                        allocation.block_id,
                    )
                    if batch_block is None:
                        raise ConflictError(
                            f"No stock exists for batch '{allocation.batch_id}' "
                            f"in block '{allocation.block_id}'."
                        )

                    planned_stock[(allocation.batch_id, allocation.block_id)] += (
                        allocation.quantity
                    )
                    resolved_allocations.append(
                        (allocation, batch_block, batch, block)
                    )

                planned_items.append(
                    (
                        delivery_item,
                        transaction_item,
                        remaining_quantity - requested_quantity,
                        resolved_allocations,
                        product,
                    )
                )

            stock_rows = {}
            for (batch_id, block_id), requested_stock in sorted(
                planned_stock.items(),
                key=lambda entry: (str(entry[0][0]), str(entry[0][1])),
            ):
                batch_block = await self.batch_block_repository.get_by_batch_and_block(
                    batch_id,
                    block_id,
                )
                if batch_block is None:
                    raise ConflictError(
                        f"No stock exists for batch '{batch_id}' in block '{block_id}'."
                    )
                if batch_block.quantity < requested_stock:
                    raise ConflictError(
                        f"Not enough stock in batch '{batch_id}' / block '{block_id}'."
                    )
                stock_rows[(batch_id, block_id)] = batch_block

            delivery = await self.sale_delivery_repository.create_delivery(
                {
                    "transaction_id": transaction_id,
                    "delivered_date": request.delivered_date,
                    "delivered_time": request.delivered_time,
                    "notes": request.notes,
                }
            )
            response_items: list[SaleDeliveryItemResponse] = []
            activity_items: list[dict[str, object]] = []
            for (
                delivery_item,
                transaction_item,
                outstanding_after_delivery,
                resolved_allocations,
                product,
            ) in planned_items:
                saved_item = await self.sale_delivery_repository.create_item(
                    {
                        "sale_delivery_id": delivery.id,
                        "transaction_item_id": transaction_item.id,
                        "quantity": Decimal(delivery_item.quantity_delivered),
                    }
                )
                if self.inventory_service is not None:
                    await self.inventory_service.append_movement(
                        farm_id=farm_id,
                        user_id=user_id,
                        product_id=transaction_item.product_id,
                        quantity_delta=-Decimal(saved_item.quantity),
                        movement_type=InventoryMovementType.SALE,
                        occurred_on=request.delivered_date,
                        notes=delivery.notes or "Chicken sale delivery",
                        source_type="sale_delivery",
                        source_id=delivery.id,
                        source_item_id=saved_item.id,
                    )
                allocation_responses = []
                for allocation, _batch_block, _batch, _block in resolved_allocations:
                    await self.sale_delivery_repository.create_allocation(
                        {
                            "sale_delivery_item_id": saved_item.id,
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
                    SaleDeliveryItemResponse(
                        id=saved_item.id,
                        transaction_item_id=transaction_item.id,
                        quantity_delivered=saved_item.quantity,
                        remaining_quantity=outstanding_after_delivery,
                        batch_allocations=allocation_responses,
                        chicken_type=transaction_item.chicken_type,
                    )
                )
                activity_items.append(
                    {
                        "product_name": product.name,
                        "quantity_delivered": str(saved_item.quantity),
                        "remaining_quantity": str(outstanding_after_delivery),
                        "chicken_type": (
                            transaction_item.chicken_type.value
                            if transaction_item.chicken_type is not None
                            else None
                        ),
                        "allocations": [
                            {
                                "quantity": str(allocation.quantity),
                                "batch_name": batch.name,
                                "block_name": block.name,
                            }
                            for (
                                allocation,
                                _batch_block,
                                batch,
                                block,
                            ) in resolved_allocations
                        ],
                    }
                )

            for key, requested_stock in planned_stock.items():
                batch_block = stock_rows[key]
                batch_block.quantity -= requested_stock
                await self.batch_block_repository.update(batch_block)

            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.SALE_DELIVERY_CREATED,
                entity_type=ActivityEntityType.SALE_DELIVERY,
                entity_id=delivery.id,
                details={
                    "transaction_id": str(transaction_id),
                    "transaction_type": transaction.transaction_type.value,
                    "reference_number": transaction.reference_number,
                    "contact_id": (
                        str(transaction.contact_id)
                        if transaction.contact_id is not None
                        else None
                    ),
                    "delivered_date": request.delivered_date.isoformat(),
                    "notes": delivery.notes,
                    "item_count": len(response_items),
                    "quantity_delivered": str(
                        sum(item.quantity_delivered for item in response_items)
                    ),
                    "items": activity_items,
                },
            )
            if commit:
                await self.unit_of_work.commit()

            logger.info(
                "sale_delivery_created",
                extra={
                    "event": "sale_delivery_created",
                    "farm_id": farm_id,
                    "user_id": user_id,
                    "transaction_id": transaction_id,
                    "delivery_id": delivery.id,
                    "item_count": len(response_items),
                },
            )
            return SaleDeliveryResponse(
                id=delivery.id,
                transaction_id=delivery.transaction_id,
                delivered_date=delivery.delivered_date,
                delivered_time=delivery.delivered_time,
                notes=delivery.notes,
                created_at=delivery.created_at,
                items=response_items,
            )

    async def get_fulfillment(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> SaleFulfillmentResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError(
                    f"Sale transaction '{transaction_id}' was not found."
                )
            self._validate_sale_transaction(transaction)
            delivered_quantities = (
                await self.sale_delivery_repository.get_delivered_quantities_by_transaction(
                    transaction_id
                )
            )
            cancelled_quantities = (
                await self.sale_return_repository.get_quantities_by_type(
                    transaction_id,
                    SaleReturnType.UNDELIVERED_CANCELLED.value,
                )
            )
            returned_quantities = (
                await self.sale_return_repository.get_quantities_by_type(
                    transaction_id,
                    SaleReturnType.DELIVERED_RETURN.value,
                )
            )
            response_items = []
            for transaction_item in transaction.items:
                product = await self.product_repository.get_by_id(
                    farm_id,
                    transaction_item.product_id,
                )
                if product is None:
                    raise ResourceNotFoundError(
                        f"Product '{transaction_item.product_id}' does not exist."
                    )
                if product.product_type != ProductType.CHICKENS:
                    continue
                ordered_quantity = self._ordered_quantity(transaction_item)
                delivered_quantity = delivered_quantities.get(
                    transaction_item.id,
                    Decimal("0"),
                )
                cancelled_quantity = cancelled_quantities.get(
                    transaction_item.id,
                    Decimal("0"),
                )
                returned_quantity = returned_quantities.get(
                    transaction_item.id,
                    Decimal("0"),
                )
                response_items.append(
                    SaleFulfillmentItemResponse(
                        transaction_item_id=transaction_item.id,
                        chicken_type=transaction_item.chicken_type,
                        ordered_quantity=ordered_quantity,
                        delivered_quantity=delivered_quantity,
                        returned_quantity=returned_quantity,
                        net_delivered_quantity=delivered_quantity - returned_quantity,
                        cancelled_quantity=cancelled_quantity,
                        outstanding_quantity=(
                            ordered_quantity - delivered_quantity - cancelled_quantity
                        ),
                    )
                )
            if not response_items:
                raise ConflictError("This sale has no chicken items to fulfill.")
            return SaleFulfillmentResponse(
                transaction_id=transaction_id,
                fully_delivered=all(
                    item.outstanding_quantity == 0 and item.cancelled_quantity == 0
                    for item in response_items
                ),
                fully_resolved=all(
                    item.outstanding_quantity == 0 for item in response_items
                ),
                items=response_items,
            )

    async def list_deliveries(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[SaleDeliveryResponse]:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError(
                    f"Sale transaction '{transaction_id}' was not found."
                )
            self._validate_sale_transaction(transaction)
            deliveries = await self.sale_delivery_repository.list_by_transaction(
                transaction_id
            )
            cumulative: defaultdict[UUID, Decimal] = defaultdict(Decimal)
            transaction_items = {item.id: item for item in transaction.items}
            response = []
            for delivery in deliveries:
                response_items = []
                for item in delivery.items:
                    transaction_item = transaction_items.get(item.transaction_item_id)
                    if transaction_item is None:
                        continue
                    cumulative[item.transaction_item_id] += item.quantity
                    ordered_quantity = self._ordered_quantity(transaction_item)
                    response_items.append(
                        SaleDeliveryItemResponse(
                            id=item.id,
                            transaction_item_id=item.transaction_item_id,
                            quantity_delivered=item.quantity,
                            remaining_quantity=(
                                ordered_quantity - cumulative[item.transaction_item_id]
                            ),
                            chicken_type=transaction_item.chicken_type,
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
                response.append(
                    SaleDeliveryResponse(
                        id=delivery.id,
                        transaction_id=delivery.transaction_id,
                        delivered_date=delivery.delivered_date,
                        delivered_time=delivery.delivered_time,
                        notes=delivery.notes,
                        created_at=delivery.created_at,
                        items=response_items,
                    )
                )
            return response

    @staticmethod
    def _validate_sale_transaction(transaction) -> None:
        if transaction.transaction_type != TransactionType.SALE:
            raise ConflictError("Fulfillment is only valid for sale transactions.")
        if transaction.status == TransactionStatus.CANCELLED:
            raise ConflictError("A cancelled sale cannot receive deliveries.")

    @staticmethod
    def _ordered_quantity(transaction_item) -> Decimal:
        ordered_quantity = (
            Decimal(str(transaction_item.quantity))
            * Decimal(str(transaction_item.conversion_factor))
        )
        if (
            ordered_quantity <= 0
            or ordered_quantity != ordered_quantity.to_integral_value()
        ):
            raise ConflictError(
                "The sale item does not represent a whole number of chickens."
            )
        return ordered_quantity

from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.repositories.product_repository import ProductRepository
from app.core.unit_of_work import UnitOfWork
from app.schemas.chicken_sale import ChickenSaleRequest
from app.schemas.enums import ProductType, TransactionStatus, TransactionType
from app.schemas.sale_delivery import (
    SaleDeliveryCreateRequest,
    SaleDeliveryBatchAllocation,
    SaleDeliveryItemRequest,
)
from app.schemas.transaction import (
    TransactionCreate,
    TransactionItemCreate,
    TransactionResponse,
)
from app.services.sale_delivery_service import SaleDeliveryService
from app.services.transaction_service import TransactionService


class ChickenSaleService:
    def __init__(
        self,
        product_repository: ProductRepository,
        transaction_service: TransactionService,
        sale_delivery_service: SaleDeliveryService,
        unit_of_work: UnitOfWork,
    ):
        self.product_repository = product_repository
        self.transaction_service = transaction_service
        self.sale_delivery_service = sale_delivery_service
        self.unit_of_work = unit_of_work

    async def create_chicken_sale(
        self,
        farm_id: UUID,
        sale_request: ChickenSaleRequest,
        user_id: UUID | None = None,
    ) -> TransactionResponse:
        transaction_items = []
        for sale_item in sale_request.items:
            product = await self.product_repository.get_by_id(
                farm_id,
                sale_item.product_id,
            )
            if product is None:
                raise ResourceNotFoundError("Product not found for this farm.")
            if not product.is_active:
                raise ConflictError("Inactive products cannot be sold.")
            if not product.is_sellable:
                raise ConflictError("This product is not marked as available for sale.")
            if product.product_type != ProductType.CHICKENS:
                raise ConflictError("Chicken sales require chicken products.")

            transaction_items.append(
                TransactionItemCreate(
                    product_id=product.id,
                    chicken_type=sale_item.chicken_type,
                    unit_id=sale_item.unit_id,
                    quantity=Decimal(sale_item.quantity),
                    unit_price=sale_item.unit_price,
                    notes=sale_item.notes,
                    batch_allocations=[
                        allocation.model_dump(mode="python")
                        for allocation in sale_item.batch_allocations
                    ],
                )
            )

        transaction_data = TransactionCreate(
            transaction_type=TransactionType.SALE,
            transaction_date=sale_request.transaction_date,
            transaction_time=sale_request.transaction_time,
            status=TransactionStatus.COMPLETED,
            contact_id=sale_request.customer_id,
            notes=sale_request.notes,
            items=transaction_items,
            payments=sale_request.payments,
            discount_type=sale_request.discount_type,
            discount_value=sale_request.discount_value,
            discount_reason=sale_request.discount_reason,
        )
        async with self.unit_of_work:
            transaction = await self.transaction_service.create_transaction(
                farm_id,
                transaction_data,
                user_id,
                commit=False,
            )
            delivery_items = []
            for sale_item, transaction_item in zip(
                sale_request.items,
                transaction.items,
                strict=True,
            ):
                if not sale_item.batch_allocations:
                    continue
                allocated_quantity = sum(
                    allocation.quantity
                    for allocation in sale_item.batch_allocations
                )
                if allocated_quantity != transaction_item.ordered_base_quantity:
                    raise ConflictError(
                        "Batch allocation totals must match the number of chickens "
                        "in each sale item."
                    )
                delivery_items.append(
                    SaleDeliveryItemRequest(
                        transaction_item_id=transaction_item.id,
                        quantity_delivered=allocated_quantity,
                        batch_allocations=[
                            SaleDeliveryBatchAllocation(
                                batch_id=allocation.batch_id,
                                block_id=allocation.block_id,
                                quantity=allocation.quantity,
                            )
                            for allocation in sale_item.batch_allocations
                        ],
                    )
                )

            if delivery_items:
                await self.sale_delivery_service.create_delivery(
                    farm_id,
                    transaction.id,
                    SaleDeliveryCreateRequest(
                        delivered_date=transaction.transaction_date,
                        delivered_time=sale_request.transaction_time,
                        items=delivery_items,
                    ),
                    user_id=user_id,
                    commit=False,
                )
            await self.unit_of_work.commit()
            return transaction

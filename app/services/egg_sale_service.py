from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.egg_loss_repository import EggLossRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.repositories.transaction_item_repository import TransactionItemRepository
from app.schemas.egg_sale import EggSaleCreateRequest
from app.schemas.enums import ProductType, TransactionType
from app.schemas.transaction import (
    TransactionCreate,
    TransactionItemCreate,
    TransactionResponse,
)
from app.services.transaction_service import TransactionService


class EggSaleService:
    def __init__(
        self,
        *,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        collection_repository: EggCollectionRepository,
        loss_repository: EggLossRepository,
        transaction_item_repository: TransactionItemRepository,
        transaction_service: TransactionService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.collection_repository = collection_repository
        self.loss_repository = loss_repository
        self.transaction_item_repository = transaction_item_repository
        self.transaction_service = transaction_service
        self.unit_of_work = unit_of_work

    async def create_sale(
        self,
        farm: Farm,
        request: EggSaleCreateRequest,
    ) -> TransactionResponse:
        async with self.unit_of_work:
            product_ids = sorted({item.product_id for item in request.items}, key=str)
            products = {}
            for product_id in product_ids:
                product = await self.product_repository.get_by_id_for_update(
                    farm.id,
                    product_id,
                )
                if product is None:
                    raise ResourceNotFoundError(
                        "An egg product in this sale was not found for this farm."
                    )
                if not product.is_active:
                    raise ConflictError("Inactive products cannot be sold.")
                if product.product_type != ProductType.EGGS:
                    raise ConflictError("Egg sales can only include egg products.")
                if not product.is_sellable:
                    raise ConflictError(
                        f"{product.name} is not marked as available for sale."
                    )
                products[product.id] = product

            requested_base_quantities: dict[UUID, Decimal] = defaultdict(
                lambda: Decimal("0.000")
            )
            transaction_items = []
            for item in request.items:
                product = products[item.product_id]
                product_unit = (
                    await self.product_unit_repository.get_by_product_and_unit(
                        product.id,
                        item.unit_id,
                    )
                )
                if product_unit is None:
                    raise ConflictError(
                        f"A selected unit is not configured for {product.name}."
                    )
                requested_base_quantities[product.id] += (
                    item.quantity * product_unit.conversion_factor
                )
                transaction_items.append(
                    TransactionItemCreate(
                        product_id=product.id,
                        unit_id=item.unit_id,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                    )
                )

            collection_totals = await self.collection_repository.get_totals_by_farm(
                farm.id
            )
            loss_totals = await self.loss_repository.get_totals_by_farm(farm.id)
            sold_totals = (
                await self.transaction_item_repository.get_sold_base_quantities_by_farm(
                    farm.id
                )
            )
            for product_id, requested_quantity in requested_base_quantities.items():
                available_quantity = max(
                    collection_totals.get(product_id, Decimal("0.000"))
                    - loss_totals.get(product_id, Decimal("0.000"))
                    - sold_totals.get(product_id, Decimal("0.000")),
                    Decimal("0.000"),
                )
                if requested_quantity > available_quantity:
                    product = products[product_id]
                    raise ConflictError(
                        f"Not enough {product.name} in stock. "
                        f"{available_quantity} base units are available; "
                        f"reduce the quantity or record more collected eggs."
                    )

            transaction_data = TransactionCreate(
                transaction_type=TransactionType.SALE,
                transaction_date=request.transaction_date,
                transaction_time=request.transaction_time,
                fulfillment_required=True,
                contact_id=request.contact_id,
                notes=request.notes,
                items=transaction_items,
                payments=request.payments,
                discount_type=request.discount_type,
                discount_value=request.discount_value,
                discount_reason=request.discount_reason,
            )
            response = await self.transaction_service.create_transaction(
                farm.id,
                transaction_data,
                farm.owner_id,
                commit=False,
            )
            await self.unit_of_work.commit()
            return response

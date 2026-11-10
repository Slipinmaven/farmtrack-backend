from decimal import Decimal
from uuid import UUID

from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.block_repository import BlockRepository
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.egg_loss_repository import EggLossRepository
from app.repositories.inventory_movement_repository import (
    InventoryMovementRepository,
)
from app.repositories.product_repository import ProductRepository
from app.repositories.transaction_item_repository import TransactionItemRepository
from app.schemas.egg_collection import (
    EggCollectionOptionsBlock,
    EggCollectionOptionsProduct,
    EggCollectionOptionsResponse,
    EggCollectionUnitOption,
)
from app.schemas.enums import InventoryMovementType, ProductType

logger = get_application_logger()


class EggCollectionOptionsService:
    def __init__(
        self,
        product_repository: ProductRepository,
        block_repository: BlockRepository,
        collection_repository: EggCollectionRepository,
        loss_repository: EggLossRepository,
        inventory_movement_repository: InventoryMovementRepository,
        transaction_item_repository: TransactionItemRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self.product_repository = product_repository
        self.block_repository = block_repository
        self.collection_repository = collection_repository
        self.loss_repository = loss_repository
        self.inventory_movement_repository = inventory_movement_repository
        self.transaction_item_repository = transaction_item_repository
        self.unit_of_work = unit_of_work

    async def get_options(self, farm: Farm) -> EggCollectionOptionsResponse:
        async with self.unit_of_work:
            products = await self.product_repository.list_by_farm(farm.id)
            collection_totals = await self.collection_repository.get_totals_by_farm(
                farm.id
            )
            collected_totals = (
                await self.collection_repository.get_collected_totals_by_farm(
                    farm.id
                )
            )
            opening_stock_totals = (
                await self.collection_repository.get_opening_stock_totals_by_farm(
                    farm.id
                )
            )
            loss_totals = await self.loss_repository.get_totals_by_farm(farm.id)
            sold_totals = (
                await self.transaction_item_repository.get_sold_base_quantities_by_farm(
                    farm.id
                )
            )
            egg_product_ids = [
                product.id
                for product in products
                if product.is_active and product.product_type == ProductType.EGGS
            ]
            reserved_totals = (
                await self.transaction_item_repository.get_reserved_base_quantities_by_farm(
                    farm.id,
                    egg_product_ids,
                )
            )
            settlement_received_totals = (
                await self.inventory_movement_repository.get_totals_by_type(
                    farm.id,
                    InventoryMovementType.SETTLEMENT_RECEIVED,
                )
            )
            settlement_issued_totals = (
                await self.inventory_movement_repository.get_totals_by_type(
                    farm.id,
                    InventoryMovementType.SETTLEMENT_ISSUED,
                )
            )
            blocks = await self.block_repository.list_by_farm(
                farm.id,
                is_active=True,
            )

            def available_quantity(product_id: UUID) -> Decimal:
                return max(
                    collection_totals.get(product_id, Decimal("0.000"))
                    - loss_totals.get(product_id, Decimal("0.000"))
                    - sold_totals.get(product_id, Decimal("0.000"))
                    + settlement_received_totals.get(
                        product_id,
                        Decimal("0.000"),
                    )
                    + settlement_issued_totals.get(
                        product_id,
                        Decimal("0.000"),
                    ),
                    Decimal("0.000"),
                )

            response = EggCollectionOptionsResponse(
                products=[
                    EggCollectionOptionsProduct(
                        id=product.id,
                        name=product.name,
                        product_type=product.product_type,
                        is_sellable=product.is_sellable,
                        units=[
                            EggCollectionUnitOption(
                                id=product_unit.unit_id,
                                name=product_unit.unit.name,
                                abbreviation=product_unit.unit.abbreviation,
                                conversion_factor=product_unit.conversion_factor,
                                is_base_unit=product_unit.is_base_unit,
                            )
                            for product_unit in product.product_units
                        ],
                        opening_stock_quantity_in_base_unit=opening_stock_totals.get(
                            product.id,
                            Decimal("0.000"),
                        ),
                        collected_quantity_in_base_unit=collected_totals.get(
                            product.id,
                            Decimal("0.000"),
                        ),
                        lost_quantity_in_base_unit=loss_totals.get(
                            product.id,
                            Decimal("0.000"),
                        ),
                        sold_quantity_in_base_unit=sold_totals.get(
                            product.id,
                            Decimal("0.000"),
                        ),
                        stock_adjustment_quantity_in_base_unit=(
                            settlement_received_totals.get(
                                product.id,
                                Decimal("0.000"),
                            )
                            + settlement_issued_totals.get(
                                product.id,
                                Decimal("0.000"),
                            )
                        ),
                        on_hand_quantity_in_base_unit=(
                            available_quantity(product.id)
                            + reserved_totals.get(product.id, Decimal("0.000"))
                        ),
                        reserved_quantity_in_base_unit=reserved_totals.get(
                            product.id,
                            Decimal("0.000"),
                        ),
                        available_quantity_in_base_unit=available_quantity(product.id),
                    )
                    for product in products
                    if product.is_active and product.product_type == ProductType.EGGS
                ],
                blocks=[
                    EggCollectionOptionsBlock(
                        id=block.id,
                        name=block.name,
                        is_active=block.is_active,
                    )
                    for block in blocks
                ],
            )
            logger.info(
                "egg_collection_options_loaded",
                extra={
                    "event": "egg_collection_options_loaded",
                    "farm_id": farm.id,
                    "user_id": farm.owner_id,
                    "product_count": len(response.products),
                    "block_count": len(response.blocks),
                },
            )
            return response
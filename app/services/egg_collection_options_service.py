from decimal import Decimal

from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.block_repository import BlockRepository
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.egg_loss_repository import EggLossRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.transaction_item_repository import TransactionItemRepository
from app.schemas.egg_collection import (
    EggCollectionOptionsBlock,
    EggCollectionOptionsProduct,
    EggCollectionOptionsResponse,
    EggCollectionUnitOption,
)
from app.schemas.enums import ProductType

logger = get_application_logger()


class EggCollectionOptionsService:
    def __init__(
        self,
        product_repository: ProductRepository,
        block_repository: BlockRepository,
        collection_repository: EggCollectionRepository,
        loss_repository: EggLossRepository,
        transaction_item_repository: TransactionItemRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self.product_repository = product_repository
        self.block_repository = block_repository
        self.collection_repository = collection_repository
        self.loss_repository = loss_repository
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
            loss_totals = await self.loss_repository.get_totals_by_farm(farm.id)
            sold_totals = (
                await self.transaction_item_repository.get_sold_base_quantities_by_farm(
                    farm.id
                )
            )
            blocks = await self.block_repository.list_by_farm(
                farm.id,
                is_active=True,
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
                        available_quantity_in_base_unit=max(
                            collection_totals.get(
                                product.id,
                                Decimal("0.000"),
                            )
                            - loss_totals.get(
                                product.id,
                                Decimal("0.000"),
                            )
                            - sold_totals.get(
                                product.id,
                                Decimal("0.000"),
                            ),
                            Decimal("0.000"),
                        ),
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
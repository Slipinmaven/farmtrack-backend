from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.inventory_movement import InventoryMovement
from app.models.chicken_batches import ChickenBatch
from app.models.egg_collections import EggCollection
from app.models.egg_losses import EggLoss
from app.models.product_consumptions import ProductConsumption
from app.models.product_units import ProductUnit
from app.models.products import Product
from app.models.transaction_items import TransactionItem
from app.models.units import Unit


class ProductRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _product_query(self):
        return select(Product).options(
            selectinload(Product.product_units).selectinload(ProductUnit.unit)
        )

    async def list_by_farm(
        self,
        farm_id: UUID,
        search: str | None = None,
    ) -> list[Product]:
        query = self._product_query().where(Product.farm_id == farm_id)
        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(Product.name.ilike(term), Product.description.ilike(term))
            )
        result = await self.session.execute(query.order_by(Product.name, Product.id))
        return list(result.scalars().all())

    async def get_by_id(self, farm_id: UUID, product_id: UUID) -> Product | None:
        result = await self.session.execute(
            self._product_query().where(
                Product.farm_id == farm_id,
                Product.id == product_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(
        self,
        farm_id: UUID,
        product_id: UUID,
    ) -> Product | None:
        result = await self.session.execute(
            select(Product)
            .where(
                Product.farm_id == farm_id,
                Product.id == product_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update_with_units(
        self,
        farm_id: UUID,
        product_id: UUID,
    ) -> Product | None:
        result = await self.session.execute(
            self._product_query()
            .where(
                Product.farm_id == farm_id,
                Product.id == product_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_units_by_ids(self, unit_ids: set[UUID]) -> dict[UUID, Unit]:
        result = await self.session.execute(select(Unit).where(Unit.id.in_(unit_ids)))
        return {unit.id: unit for unit in result.scalars().all()}

    async def has_inventory_movements(self, farm_id: UUID, product_id: UUID) -> bool:
        result = await self.session.execute(
            select(InventoryMovement.id)
            .where(
                InventoryMovement.farm_id == farm_id,
                InventoryMovement.product_id == product_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def has_product_history(self, product_id: UUID) -> bool:
        history_checks = (
            select(InventoryMovement.id)
            .where(InventoryMovement.product_id == product_id)
            .exists(),
            select(TransactionItem.id)
            .where(TransactionItem.product_id == product_id)
            .exists(),
            select(ChickenBatch.id)
            .where(ChickenBatch.product_id == product_id)
            .exists(),
            select(EggCollection.id)
            .where(EggCollection.product_id == product_id)
            .exists(),
            select(EggLoss.id)
            .where(EggLoss.product_id == product_id)
            .exists(),
            select(ProductConsumption.id)
            .where(ProductConsumption.product_id == product_id)
            .exists(),
        )
        result = await self.session.execute(select(or_(*history_checks)))
        return result.scalar_one()

    async def create(
        self,
        farm_id: UUID,
        product_data: dict,
        unit_definitions: list[tuple[Unit, dict]],
    ) -> Product:
        product = Product(farm_id=farm_id, **product_data)
        product.product_units = [
            ProductUnit(
                unit=unit,
                conversion_factor=definition["conversion_factor"],
                is_base_unit=definition["is_base_unit"],
            )
            for unit, definition in unit_definitions
        ]
        self.session.add(product)
        await self.session.flush()
        return product

    async def update(
        self,
        product: Product,
        product_data: dict,
        unit_definitions: list[tuple[Unit, dict]] | None,
    ) -> Product:
        for field, value in product_data.items():
            setattr(product, field, value)
        if unit_definitions is not None:
            product.product_units.clear()
            await self.session.flush()
            product.product_units = [
                ProductUnit(
                    unit=unit,
                    conversion_factor=definition["conversion_factor"],
                    is_base_unit=definition["is_base_unit"],
                )
                for unit, definition in unit_definitions
            ]
        await self.session.flush()
        await self.session.refresh(product, attribute_names=["updated_at"])
        return product

    async def delete(self, product: Product) -> None:
        await self.session.delete(product)
        await self.session.flush()

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory_movement import InventoryMovement
from app.models.products import Product
from app.models.product_units import ProductUnit
from app.models.units import Unit


class InventoryMovementRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_balance(self, farm_id: UUID, product_id: UUID) -> Decimal:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(InventoryMovement.quantity_delta), 0)
            ).where(
                InventoryMovement.farm_id == farm_id,
                InventoryMovement.product_id == product_id,
            )
        )
        return Decimal(result.scalar_one())

    async def has_opening_balance(self, farm_id: UUID, product_id: UUID) -> bool:
        result = await self.session.execute(
            select(InventoryMovement.id)
            .where(
                InventoryMovement.farm_id == farm_id,
                InventoryMovement.product_id == product_id,
                InventoryMovement.movement_type == "opening_balance",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def has_movements(self, farm_id: UUID, product_id: UUID) -> bool:
        result = await self.session.execute(
            select(InventoryMovement.id)
            .where(
                InventoryMovement.farm_id == farm_id,
                InventoryMovement.product_id == product_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_balances(self, farm_id: UUID) -> list[tuple]:
        result = await self.session.execute(
            select(
                Product.id,
                Product.name,
                Product.product_type,
                func.coalesce(func.sum(InventoryMovement.quantity_delta), 0),
                Unit.name,
                Unit.abbreviation,
            )
            .join(ProductUnit, ProductUnit.product_id == Product.id)
            .join(Unit, Unit.id == ProductUnit.unit_id)
            .outerjoin(
                InventoryMovement,
                (InventoryMovement.product_id == Product.id)
                & (InventoryMovement.farm_id == farm_id),
            )
            .where(
                Product.farm_id == farm_id,
                ProductUnit.is_base_unit.is_(True),
            )
            .group_by(
                Product.id,
                Product.name,
                Product.product_type,
                Unit.name,
                Unit.abbreviation,
            )
            .order_by(Product.name, Product.id)
        )
        return list(result.all())

    async def list_movements(
        self,
        farm_id: UUID,
        *,
        product_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple]:
        query = (
            select(InventoryMovement, Product, Unit)
            .join(Product, Product.id == InventoryMovement.product_id)
            .join(Unit, Unit.id == InventoryMovement.unit_id)
            .where(InventoryMovement.farm_id == farm_id)
        )
        if product_id is not None:
            query = query.where(InventoryMovement.product_id == product_id)
        result = await self.session.execute(
            query.order_by(
                InventoryMovement.occurred_on.desc(),
                InventoryMovement.created_at.desc(),
                InventoryMovement.id,
            ).limit(limit).offset(offset)
        )
        return list(result.all())

    async def list_product_cost_movements(
        self,
        farm_id: UUID,
        product_id: UUID,
        *,
        as_of: date | None = None,
    ) -> list[InventoryMovement]:
        query = select(InventoryMovement).where(
            InventoryMovement.farm_id == farm_id,
            InventoryMovement.product_id == product_id,
        )
        if as_of is not None:
            query = query.where(InventoryMovement.occurred_on <= as_of)
        result = await self.session.execute(
            query.order_by(
                InventoryMovement.occurred_on,
                InventoryMovement.created_at,
                InventoryMovement.id,
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        farm_id: UUID,
        user_id: UUID | None,
        product_id: UUID,
        unit_id: UUID,
        quantity_delta: Decimal,
        movement_type: str,
        occurred_on: date,
        notes: str,
        source_type: str | None = None,
        source_id: UUID | None = None,
        source_item_id: UUID | None = None,
        unit_cost: Decimal | None = None,
    ) -> InventoryMovement:
        movement = InventoryMovement(
            farm_id=farm_id,
            user_id=user_id,
            product_id=product_id,
            unit_id=unit_id,
            quantity_delta=quantity_delta,
            movement_type=movement_type,
            occurred_on=occurred_on,
            notes=notes,
            source_type=source_type,
            source_id=source_id,
            source_item_id=source_item_id,
            unit_cost=unit_cost,
        )
        self.session.add(movement)
        await self.session.flush()
        return movement

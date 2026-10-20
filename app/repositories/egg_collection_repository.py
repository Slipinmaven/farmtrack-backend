from datetime import datetime
from uuid import UUID

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.egg_collections import EggCollection
from app.models.units import Unit


class EggCollectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_units_by_collection_ids(
        self,
        farm_id: UUID,
        collection_ids: list[UUID],
    ) -> dict[UUID, tuple[str, str]]:
        if not collection_ids:
            return {}

        result = await self.session.execute(
            select(EggCollection.id, Unit.name, Unit.abbreviation)
            .join(Unit, Unit.id == EggCollection.unit_id)
            .where(
                EggCollection.farm_id == farm_id,
                EggCollection.id.in_(collection_ids),
            )
        )
        return {
            collection_id: (unit_name, unit_abbreviation)
            for collection_id, unit_name, unit_abbreviation in result.all()
        }

    async def list_by_farm(
        self,
        farm_id: UUID,
        *,
        product_id: UUID | None = None,
        block_id: UUID | None = None,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
    ) -> list[EggCollection]:
        query = select(EggCollection).where(EggCollection.farm_id == farm_id)
        if product_id is not None:
            query = query.where(EggCollection.product_id == product_id)
        if block_id is not None:
            query = query.where(EggCollection.block_id == block_id)
        if from_datetime is not None:
            query = query.where(EggCollection.collected_at >= from_datetime)
        if to_datetime is not None:
            query = query.where(EggCollection.collected_at <= to_datetime)
        result = await self.session.execute(
            query.order_by(
                EggCollection.collected_at.desc(),
                EggCollection.created_at.desc(),
                EggCollection.id,
            )
        )
        return list(result.scalars().all())

    async def get_total_base_quantity(
        self,
        farm_id: UUID,
        product_id: UUID,
    ) -> Decimal:
        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(EggCollection.quantity * EggCollection.conversion_factor),
                    0,
                )
            ).where(
                EggCollection.farm_id == farm_id,
                EggCollection.product_id == product_id,
            )
        )
        return Decimal(result.scalar_one())

    async def get_totals_by_farm(self, farm_id: UUID) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(
                EggCollection.product_id,
                func.coalesce(
                    func.sum(EggCollection.quantity * EggCollection.conversion_factor),
                    0,
                ),
            )
            .where(EggCollection.farm_id == farm_id)
            .group_by(EggCollection.product_id)
        )
        return {
            product_id: Decimal(quantity)
            for product_id, quantity in result.all()
        }

    async def get_collected_totals_by_farm(
        self,
        farm_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(
                EggCollection.product_id,
                func.coalesce(
                    func.sum(EggCollection.quantity * EggCollection.conversion_factor),
                    0,
                ),
            )
            .where(
                EggCollection.farm_id == farm_id,
                EggCollection.entry_type == "collection",
            )
            .group_by(EggCollection.product_id)
        )
        return {
            product_id: Decimal(quantity)
            for product_id, quantity in result.all()
        }

    async def create_many(
        self,
        farm_id: UUID,
        records: list[dict],
    ) -> list[EggCollection]:
        collections = [
            EggCollection(farm_id=farm_id, **record)
            for record in records
        ]
        self.session.add_all(collections)
        await self.session.flush()
        return collections
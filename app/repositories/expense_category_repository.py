from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expense_category import ExpenseCategoryRecord


class ExpenseCategoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_farm(
        self,
        farm_id: UUID,
        *,
        include_inactive: bool = False,
    ) -> list[ExpenseCategoryRecord]:
        query = select(ExpenseCategoryRecord).where(
            ExpenseCategoryRecord.farm_id == farm_id
        )
        if not include_inactive:
            query = query.where(ExpenseCategoryRecord.is_active.is_(True))
        result = await self.session.execute(
            query.order_by(
                ExpenseCategoryRecord.is_default.desc(),
                ExpenseCategoryRecord.name,
                ExpenseCategoryRecord.id,
            )
        )
        return list(result.scalars().all())

    async def get_by_key(
        self,
        farm_id: UUID,
        key: str,
    ) -> ExpenseCategoryRecord | None:
        result = await self.session.execute(
            select(ExpenseCategoryRecord).where(
                ExpenseCategoryRecord.farm_id == farm_id,
                ExpenseCategoryRecord.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        farm_id: UUID,
        category_id: UUID,
    ) -> ExpenseCategoryRecord | None:
        result = await self.session.execute(
            select(ExpenseCategoryRecord).where(
                ExpenseCategoryRecord.farm_id == farm_id,
                ExpenseCategoryRecord.id == category_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, farm_id: UUID, data: dict) -> ExpenseCategoryRecord:
        category = ExpenseCategoryRecord(farm_id=farm_id, **data)
        self.session.add(category)
        await self.session.flush()
        return category

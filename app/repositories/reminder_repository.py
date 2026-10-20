from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminders import Reminder
from app.schemas.enums import ReminderStatus


class ReminderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, farm_id: UUID, data: dict) -> Reminder:
        reminder = Reminder(farm_id=farm_id, **data)
        self.session.add(reminder)
        await self.session.flush()
        return reminder

    async def list_by_farm(self, farm_id: UUID) -> list[Reminder]:
        result = await self.session.execute(
            select(Reminder)
            .where(Reminder.farm_id == farm_id)
            .order_by(Reminder.due_at, Reminder.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id_for_farm(
        self,
        farm_id: UUID,
        reminder_id: UUID,
        *,
        for_update: bool = False,
    ) -> Reminder | None:
        query = select(Reminder).where(
            Reminder.farm_id == farm_id,
            Reminder.id == reminder_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_due_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[Reminder]:
        current_time = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            select(Reminder)
            .where(
                Reminder.status == ReminderStatus.PENDING.value,
                Reminder.due_at <= current_time,
                Reminder.notification_enqueued_at.is_(None),
            )
            .order_by(Reminder.due_at, Reminder.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())
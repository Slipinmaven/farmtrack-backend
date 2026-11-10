from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_outbox import NotificationOutbox


class NotificationOutboxRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(
        self,
        *,
        farm_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        dedupe_key: str,
    ) -> None:
        statement = (
            insert(NotificationOutbox)
            .values(
                farm_id=farm_id,
                event_type=event_type,
                payload=payload,
                dedupe_key=dedupe_key,
            )
            .on_conflict_do_nothing(index_elements=[NotificationOutbox.dedupe_key])
        )
        await self.session.execute(statement)

    async def claim_one(self, now: datetime | None = None) -> NotificationOutbox | None:
        current_time = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.processed_at.is_(None),
                NotificationOutbox.failed_at.is_(None),
                NotificationOutbox.available_at <= current_time,
            )
            .order_by(NotificationOutbox.available_at, NotificationOutbox.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result.scalar_one_or_none()

    async def record_failure(
        self,
        event_id: UUID,
        *,
        now: datetime,
        max_attempts: int,
        error_summary: str,
    ) -> bool:
        event = await self.session.get(NotificationOutbox, event_id, with_for_update=True)
        if event is None or event.processed_at is not None:
            return False
        event.attempts += 1
        event.last_error = error_summary[:500]
        if event.attempts >= max_attempts:
            event.failed_at = now
            return True
        delay_seconds = min(2 ** min(event.attempts, 12), 3600)
        event.available_at = now + timedelta(seconds=delay_seconds)
        await self.session.flush()
        return False
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import Notification
from app.schemas.enums import NotificationCategory


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: dict) -> Notification:
        notification = Notification(**data)
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def create_for_source_event(self, data: dict) -> None:
        statement = (
            insert(Notification)
            .values(**data)
            .on_conflict_do_nothing(index_elements=[Notification.source_event_id])
        )
        await self.session.execute(statement)

    async def list_for_recipient(
        self,
        *,
        farm_id: UUID,
        recipient_user_id: UUID,
        limit: int,
        cursor: tuple[datetime, UUID] | None = None,
        unread_only: bool = False,
        category: NotificationCategory | None = None,
        now: datetime | None = None,
    ) -> list[Notification]:
        current_time = now or datetime.now(timezone.utc)
        query = select(Notification).where(
            Notification.farm_id == farm_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.archived_at.is_(None),
            or_(Notification.expires_at.is_(None), Notification.expires_at > current_time),
        )
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        if category is not None:
            query = query.where(Notification.category == category)
        if cursor is not None:
            cursor_created_at, cursor_id = cursor
            query = query.where(
                or_(
                    Notification.created_at < cursor_created_at,
                    and_(
                        Notification.created_at == cursor_created_at,
                        Notification.id < cursor_id,
                    ),
                )
            )
        result = await self.session.execute(
            query.order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_unread(
        self,
        *,
        farm_id: UUID,
        recipient_user_id: UUID,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            select(func.count(Notification.id)).where(
                Notification.farm_id == farm_id,
                Notification.recipient_user_id == recipient_user_id,
                Notification.read_at.is_(None),
                Notification.archived_at.is_(None),
                or_(Notification.expires_at.is_(None), Notification.expires_at > current_time),
            )
        )
        return int(result.scalar_one())

    async def get_for_recipient(
        self,
        *,
        farm_id: UUID,
        recipient_user_id: UUID,
        notification_id: UUID,
        for_update: bool = False,
    ) -> Notification | None:
        query = select(Notification).where(
            Notification.id == notification_id,
            Notification.farm_id == farm_id,
            Notification.recipient_user_id == recipient_user_id,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def mark_all_read(
        self,
        *,
        farm_id: UUID,
        recipient_user_id: UUID,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.farm_id == farm_id,
                Notification.recipient_user_id == recipient_user_id,
                Notification.read_at.is_(None),
                Notification.archived_at.is_(None),
            )
            .values(read_at=current_time)
        )
        return int(result.rowcount or 0)
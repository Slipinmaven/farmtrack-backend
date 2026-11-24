import base64
import binascii
import json
from datetime import datetime, timezone
from uuid import UUID

from app.core.exceptions import InvalidNotificationCursorError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.notification_repository import NotificationRepository
from app.schemas.enums import NotificationCategory
from app.schemas.notification import (
    NotificationListResponse,
    NotificationMutationResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)

logger = get_application_logger()


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self.repository = repository
        self.unit_of_work = unit_of_work

    async def list_notifications(
        self,
        farm: Farm,
        *,
        recipient_user_id: UUID,
        limit: int,
        cursor: str | None = None,
        unread_only: bool = False,
        category: NotificationCategory | None = None,
    ) -> NotificationListResponse:
        decoded_cursor = self._decode_cursor(cursor) if cursor is not None else None
        async with self.unit_of_work:
            rows = await self.repository.list_for_recipient(
                farm_id=farm.id,
                recipient_user_id=recipient_user_id,
                limit=limit + 1,
                cursor=decoded_cursor,
                unread_only=unread_only,
                category=category,
            )
            has_more = len(rows) > limit
            page = rows[:limit]
            next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
            return NotificationListResponse(
                items=[
                    NotificationResponse.model_validate(row, from_attributes=True)
                    for row in page
                ],
                next_cursor=next_cursor,
            )

    async def unread_count(
        self,
        farm: Farm,
        *,
        recipient_user_id: UUID,
    ) -> NotificationUnreadCountResponse:
        async with self.unit_of_work:
            count = await self.repository.count_unread(
                farm_id=farm.id,
                recipient_user_id=recipient_user_id,
            )
            return NotificationUnreadCountResponse(unread_count=count)

    async def mark_read(
        self,
        farm: Farm,
        *,
        recipient_user_id: UUID,
        notification_id: UUID,
    ) -> NotificationResponse:
        async with self.unit_of_work:
            notification = await self.repository.get_for_recipient(
                farm_id=farm.id,
                recipient_user_id=recipient_user_id,
                notification_id=notification_id,
                for_update=True,
            )
            if notification is None:
                raise ResourceNotFoundError("Notification not found.")
            if notification.read_at is None:
                notification.read_at = datetime.now(timezone.utc)
                await self.unit_of_work.flush()
                await self.unit_of_work.commit()
            return NotificationResponse.model_validate(
                notification,
                from_attributes=True,
            )

    async def mark_all_read(
        self,
        farm: Farm,
        *,
        recipient_user_id: UUID,
    ) -> NotificationMutationResponse:
        async with self.unit_of_work:
            updated_count = await self.repository.mark_all_read(
                farm_id=farm.id,
                recipient_user_id=recipient_user_id,
            )
            await self.unit_of_work.commit()
            return NotificationMutationResponse(updated_count=updated_count)

    async def archive(
        self,
        farm: Farm,
        *,
        recipient_user_id: UUID,
        notification_id: UUID,
    ) -> NotificationResponse:
        async with self.unit_of_work:
            notification = await self.repository.get_for_recipient(
                farm_id=farm.id,
                recipient_user_id=recipient_user_id,
                notification_id=notification_id,
                for_update=True,
            )
            if notification is None:
                raise ResourceNotFoundError("Notification not found.")
            if notification.archived_at is None:
                notification.archived_at = datetime.now(timezone.utc)
                await self.unit_of_work.flush()
                await self.unit_of_work.commit()
            return NotificationResponse.model_validate(
                notification,
                from_attributes=True,
            )

    @staticmethod
    def _encode_cursor(notification) -> str:
        payload = json.dumps(
            {
                "created_at": notification.created_at.isoformat(),
                "id": str(notification.id),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            created_at = datetime.fromisoformat(payload["created_at"])
            notification_id = UUID(payload["id"])
            if created_at.tzinfo is None:
                raise ValueError("Cursor timestamp must include timezone.")
            return created_at, notification_id
        except (
            binascii.Error,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            raise InvalidNotificationCursorError() from None
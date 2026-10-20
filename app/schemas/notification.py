from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import NotificationCategory, NotificationPriority


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    recipient_user_id: UUID
    source_event_id: UUID
    type: str
    category: NotificationCategory
    priority: NotificationPriority
    title: str
    message: str
    entity_type: str | None
    entity_id: UUID | None
    payload: dict[str, Any] | None
    created_at: datetime
    read_at: datetime | None
    archived_at: datetime | None
    expires_at: datetime | None


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    next_cursor: str | None


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationMutationResponse(BaseModel):
    updated_count: int
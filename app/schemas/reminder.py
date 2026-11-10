from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import ReminderStatus


class ReminderCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    due_at: datetime
    delivery_channel: Literal["in_app", "push"] = "in_app"
    expo_push_token: str | None = Field(default=None, max_length=255)
    recurrence_rule: dict[str, Any] | None = None
    related_entity_type: str | None = Field(default=None, max_length=100)
    related_entity_id: UUID | None = None


class ReminderRescheduleRequest(BaseModel):
    due_at: datetime


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    title: str
    description: str | None
    due_at: datetime
    delivery_channel: Literal["in_app", "push"] = "in_app"
    status: ReminderStatus
    recurrence_rule: dict[str, Any] | None
    related_entity_type: str | None
    related_entity_id: UUID | None
    created_at: datetime
    completed_at: datetime | None
    notification_enqueued_at: datetime | None
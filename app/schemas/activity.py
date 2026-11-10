from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import ActivityCategory, ActivityEntityType, ActivityType


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    user_id: UUID | None
    session_id: UUID | None
    type: ActivityType
    entity_type: ActivityEntityType
    entity_id: UUID
    details: dict[str, object] | None
    created_at: datetime


class ActivityFeedResponse(BaseModel):
    items: list[ActivityResponse]
    next_cursor: str | None
    has_more: bool
    total_count: int | None = None


class ActivitySummaryResponse(BaseModel):
    last_7_days_count: int
    previous_7_days_count: int
    losses_and_returns_count: int
    category_counts: dict[ActivityCategory, int]
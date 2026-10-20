from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import ChickenLossReason

PositiveQuantity = Annotated[int, Field(gt=0)]


class ChickenLossItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    block_id: UUID
    quantity: PositiveQuantity
    reason: ChickenLossReason
    notes: str | None = None


class ChickenLossCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loss_date: date
    items: list[ChickenLossItemRequest] = Field(min_length=1)


class ChickenLossResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    batch_id: UUID
    block_id: UUID
    quantity: int
    loss_date: date
    reason: ChickenLossReason
    notes: str | None
    created_at: datetime
    updated_at: datetime
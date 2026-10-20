from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveQuantity = Annotated[int, Field(gt=0)]
MovementReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class ChickenMovementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    from_block_id: UUID
    to_block_id: UUID
    quantity: PositiveQuantity
    movement_date: date
    reason: MovementReason | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_blocks(self) -> "ChickenMovementCreateRequest":
        if self.from_block_id == self.to_block_id:
            raise ValueError("from_block_id and to_block_id must be different.")
        return self


class ChickenMovementBatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    quantity: PositiveQuantity


class ChickenMovementBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_block_id: UUID
    to_block_id: UUID
    movement_date: date
    items: list[ChickenMovementBatchItemRequest] = Field(min_length=1)
    reason: MovementReason | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_movement(self) -> "ChickenMovementBatchCreateRequest":
        if self.from_block_id == self.to_block_id:
            raise ValueError("from_block_id and to_block_id must be different.")
        batch_ids = [item.batch_id for item in self.items]
        if len(batch_ids) != len(set(batch_ids)):
            raise ValueError("Each batch can only appear once in a movement.")
        return self


class ChickenMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    batch_id: UUID
    from_block_id: UUID
    to_block_id: UUID
    quantity: int
    movement_date: date
    reason: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ChickenMovementHistoryItem(BaseModel):
    id: UUID
    batch_id: UUID
    batch_name: str
    from_block_id: UUID
    from_block_name: str
    to_block_id: UUID
    to_block_name: str
    quantity: int
    movement_date: date
    reason: str | None
    notes: str | None


class ChickenMovementHistoryResponse(BaseModel):
    items: list[ChickenMovementHistoryItem]
    total_count: int
    limit: int
    offset: int


MovementDirection = Literal["all", "incoming", "outgoing"]
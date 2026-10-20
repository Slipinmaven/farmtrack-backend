from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChickenBatchNameCounter(Base):
    __tablename__ = "chicken_batch_name_counters"
    __table_args__ = (
        UniqueConstraint(
            "farm_id",
            "batch_date",
            name="uq_chicken_batch_name_counters_farm_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    batch_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
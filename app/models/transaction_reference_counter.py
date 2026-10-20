from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TransactionReferenceCounter(Base):
    __tablename__ = "transaction_reference_counters"
    __table_args__ = (
        UniqueConstraint(
            "farm_id",
            "reference_type",
            "reference_date",
            name="uq_transaction_reference_counters_scope",
        ),
        CheckConstraint("last_number >= 0", name="ck_transaction_reference_counter_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    reference_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EggProductionCostConfirmation(Base):
    __tablename__ = "egg_production_cost_confirmations"
    __table_args__ = (
        CheckConstraint("from_date <= to_date", name="ck_egg_prod_cost_confirmation_dates"),
        UniqueConstraint(
            "farm_id",
            "from_date",
            "to_date",
            name="uq_egg_prod_cost_confirmation_period",
        ),
        Index(
            "ix_egg_prod_cost_confirmation_farm_period",
            "farm_id",
            "from_date",
            "to_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

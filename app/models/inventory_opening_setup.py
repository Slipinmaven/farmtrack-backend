from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InventoryOpeningSetup(Base):
    __tablename__ = "inventory_opening_setups"
    __table_args__ = (
        UniqueConstraint("farm_id", "species", name="uq_inventory_opening_farm_species"),
        CheckConstraint(
            "species IN ('chickens', 'eggs')",
            name="ck_inventory_opening_species",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    species: Mapped[str] = mapped_column(String(16), nullable=False)
    setup_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.enums import InventoryMovementType

class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "quantity_delta <> 0 OR movement_type = 'valuation'",
            name="ck_inventory_movements_quantity_non_zero",
        ),
        CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0",
            name="ck_inventory_movements_unit_cost_non_negative",
        ),
        CheckConstraint(
            "movement_type <> 'valuation' OR unit_cost IS NOT NULL",
            name="ck_inventory_movements_valuation_has_cost",
        ),
        CheckConstraint(
            "movement_type IN "
            "('opening_balance', 'receipt', 'sale', 'consumption', 'loss', "
            "'customer_return', 'supplier_return', 'settlement_received', "
            "'settlement_issued', 'adjustment', 'valuation')",
            name="ck_inventory_movements_type_valid",
        ),
        Index(
            "ix_inventory_movements_farm_product_created",
            "farm_id",
            "product_id",
            "created_at",
        ),
        Index(
            "ix_inventory_movements_farm_occurred",
            "farm_id",
            "occurred_on",
        ),
        Index(
            "ix_inventory_movements_source",
            "source_type",
            "source_id",
            "source_item_id",
        ),
        Index(
            "uq_inventory_movements_source_item",
            "farm_id",
            "source_type",
            "source_id",
            "source_item_id",
            unique=True,
            postgresql_where=text(
                "source_type IS NOT NULL AND source_id IS NOT NULL "
                "AND source_item_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    unit_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("units.id"), nullable=False
    )
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    movement_type: Mapped[InventoryMovementType] = mapped_column(
        String(32), nullable=False
    )
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_item_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

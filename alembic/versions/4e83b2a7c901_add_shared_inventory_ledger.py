"""add shared inventory ledger

Revision ID: 4e83b2a7c901
Revises: 2a7c9d4e6f10
Create Date: 2026-10-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4e83b2a7c901"
down_revision: Union[str, Sequence[str], None] = "2a7c9d4e6f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'INVENTORY_ADJUSTED'")
    op.execute(
        "ALTER TYPE activitytype "
        "ADD VALUE IF NOT EXISTS 'TRANSACTION_SETTLEMENT_RECORDED'"
    )
    op.execute(
        "ALTER TYPE activityentitytype "
        "ADD VALUE IF NOT EXISTS 'INVENTORY_MOVEMENT'"
    )
    op.execute(
        "ALTER TYPE activityentitytype "
        "ADD VALUE IF NOT EXISTS 'TRANSACTION_SETTLEMENT'"
    )

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(14, 3), nullable=False),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("source_item_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_delta <> 0",
            name="ck_inventory_movements_quantity_non_zero",
        ),
        sa.CheckConstraint(
            "movement_type IN "
            "('opening_balance', 'receipt', 'sale', 'consumption', 'loss', "
            "'customer_return', 'supplier_return', 'settlement_received', "
            "'settlement_issued', 'adjustment')",
            name="ck_inventory_movements_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"], ["farms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inventory_movements_farm_product_created",
        "inventory_movements",
        ["farm_id", "product_id", "created_at"],
    )
    op.create_index(
        "ix_inventory_movements_source",
        "inventory_movements",
        ["source_type", "source_id", "source_item_id"],
    )
    op.create_index(
        "uq_inventory_movements_source_item",
        "inventory_movements",
        ["farm_id", "source_type", "source_id", "source_item_id"],
        unique=True,
        postgresql_where=sa.text(
            "source_type IS NOT NULL AND source_id IS NOT NULL "
            "AND source_item_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_inventory_movements_source_item",
        table_name="inventory_movements",
    )
    op.drop_index("ix_inventory_movements_source", table_name="inventory_movements")
    op.drop_index(
        "ix_inventory_movements_farm_product_created",
        table_name="inventory_movements",
    )
    op.drop_table("inventory_movements")

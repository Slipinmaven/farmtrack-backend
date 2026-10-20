"""add sale delivery fulfillment ledger

Revision ID: f2a1b6d48c90
Revises: bcddeed07966
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a1b6d48c90"
down_revision: Union[str, Sequence[str], None] = "bcddeed07966"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'SALE_DELIVERY_CREATED'")
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'SALE_DELIVERY'")

    op.create_table(
        "sale_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("delivered_date", sa.Date(), nullable=False),
        sa.Column("delivered_time", sa.Time(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sale_deliveries_transaction_id",
        "sale_deliveries",
        ["transaction_id"],
    )
    op.create_index(
        "ix_sale_deliveries_delivered_date",
        "sale_deliveries",
        ["delivered_date"],
    )

    op.create_table(
        "sale_delivery_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sale_delivery_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_sale_delivery_items_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["sale_delivery_id"], ["sale_deliveries.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["transaction_item_id"], ["transaction_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sale_delivery_items_delivery_id",
        "sale_delivery_items",
        ["sale_delivery_id"],
    )
    op.create_index(
        "ix_sale_delivery_items_transaction_item_id",
        "sale_delivery_items",
        ["transaction_item_id"],
    )

    op.create_table(
        "sale_delivery_item_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sale_delivery_item_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_sale_delivery_item_allocations_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["sale_delivery_item_id"],
            ["sale_delivery_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sale_delivery_item_id",
            "batch_id",
            "block_id",
            name="uq_sale_delivery_item_allocations_item_batch_block",
        ),
    )
    op.create_index(
        "ix_sale_delivery_item_allocations_block_id",
        "sale_delivery_item_allocations",
        ["block_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sale_delivery_item_allocations_block_id",
        table_name="sale_delivery_item_allocations",
    )
    op.drop_table("sale_delivery_item_allocations")
    op.drop_index(
        "ix_sale_delivery_items_transaction_item_id",
        table_name="sale_delivery_items",
    )
    op.drop_index(
        "ix_sale_delivery_items_delivery_id",
        table_name="sale_delivery_items",
    )
    op.drop_table("sale_delivery_items")
    op.drop_index("ix_sale_deliveries_delivered_date", table_name="sale_deliveries")
    op.drop_index("ix_sale_deliveries_transaction_id", table_name="sale_deliveries")
    op.drop_table("sale_deliveries")
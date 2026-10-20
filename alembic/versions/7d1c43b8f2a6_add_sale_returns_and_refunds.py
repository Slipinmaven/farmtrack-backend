"""add sale returns and transaction refunds

Revision ID: 7d1c43b8f2a6
Revises: f2a1b6d48c90
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7d1c43b8f2a6"
down_revision: Union[str, Sequence[str], None] = "f2a1b6d48c90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

payment_method = postgresql.ENUM(
    "CASH",
    "MPESA",
    "BANK_TRANSFER",
    "CARD",
    "OTHER",
    name="paymentmethod",
    create_type=False,
)


def upgrade() -> None:
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'SALE_RETURN_CREATED'")
    op.execute(
        "ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'TRANSACTION_REFUND_CREATED'"
    )
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'SALE_RETURN'")
    op.execute(
        "ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'TRANSACTION_REFUND'"
    )

    op.create_table(
        "sale_returns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("return_type", sa.String(length=32), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("return_time", sa.Time(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
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
        sa.CheckConstraint(
            "return_type IN ('undelivered_cancelled', 'delivered_return')",
            name="ck_sale_returns_type_valid",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sale_returns_transaction_id",
        "sale_returns",
        ["transaction_id"],
    )

    op.create_table(
        "sale_return_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sale_return_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("credit_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_sale_return_items_quantity_positive",
        ),
        sa.CheckConstraint(
            "credit_amount >= 0",
            name="ck_sale_return_items_credit_amount_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["sale_return_id"], ["sale_returns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["transaction_item_id"], ["transaction_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sale_return_items_return_id",
        "sale_return_items",
        ["sale_return_id"],
    )
    op.create_index(
        "ix_sale_return_items_transaction_item_id",
        "sale_return_items",
        ["transaction_item_id"],
    )

    op.create_table(
        "sale_return_item_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sale_return_item_id", sa.Uuid(), nullable=False),
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
            name="ck_sale_return_item_allocations_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["sale_return_item_id"],
            ["sale_return_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sale_return_item_id",
            "batch_id",
            "block_id",
            name="uq_sale_return_item_allocations_item_batch_block",
        ),
    )
    op.create_index(
        "ix_sale_return_item_allocations_block_id",
        "sale_return_item_allocations",
        ["block_id"],
    )

    op.create_table(
        "transaction_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("refund_date", sa.Date(), nullable=False),
        sa.Column("refund_time", sa.Time(), nullable=True),
        sa.Column("payment_method", payment_method, nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
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
        sa.CheckConstraint("amount > 0", name="ck_transaction_refunds_amount_positive"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transaction_refunds_transaction_id",
        "transaction_refunds",
        ["transaction_id"],
    )
    op.create_index(
        "ix_transaction_refunds_refund_date",
        "transaction_refunds",
        ["refund_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_transaction_refunds_refund_date", table_name="transaction_refunds")
    op.drop_index(
        "ix_transaction_refunds_transaction_id",
        table_name="transaction_refunds",
    )
    op.drop_table("transaction_refunds")
    op.drop_index(
        "ix_sale_return_item_allocations_block_id",
        table_name="sale_return_item_allocations",
    )
    op.drop_table("sale_return_item_allocations")
    op.drop_index(
        "ix_sale_return_items_transaction_item_id",
        table_name="sale_return_items",
    )
    op.drop_index(
        "ix_sale_return_items_return_id",
        table_name="sale_return_items",
    )
    op.drop_table("sale_return_items")
    op.drop_index("ix_sale_returns_transaction_id", table_name="sale_returns")
    op.drop_table("sale_returns")
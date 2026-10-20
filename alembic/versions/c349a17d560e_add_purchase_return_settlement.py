"""add purchase return and supplier settlement ledgers

Revision ID: c349a17d560e
Revises: 7d1c43b8f2a6
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c349a17d560e"
down_revision: Union[str, Sequence[str], None] = "7d1c43b8f2a6"
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
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'PURCHASE_RETURN_CREATED'")
    op.execute(
        "ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'PURCHASE_SUPPLIER_REFUND_RECORDED'"
    )
    op.execute(
        "ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'PURCHASE_REPLACEMENT_RECEIVED'"
    )
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'PURCHASE_RETURN'")
    op.execute(
        "ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'PURCHASE_SUPPLIER_REFUND'"
    )
    op.execute(
        "ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'PURCHASE_REPLACEMENT'"
    )

    op.create_table(
        "purchase_returns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_returns_transaction_id",
        "purchase_returns",
        ["transaction_id"],
    )

    op.create_table(
        "purchase_return_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_return_id", sa.Uuid(), nullable=False),
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
            name="ck_purchase_return_items_quantity_positive",
        ),
        sa.CheckConstraint(
            "credit_amount >= 0",
            name="ck_purchase_return_items_credit_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_return_id"], ["purchase_returns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["transaction_item_id"], ["transaction_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_return_id",
            "transaction_item_id",
            name="uq_purchase_return_items_return_transaction_item",
        ),
    )
    op.create_index(
        "ix_purchase_return_items_return_id",
        "purchase_return_items",
        ["purchase_return_id"],
    )
    op.create_index(
        "ix_purchase_return_items_transaction_item_id",
        "purchase_return_items",
        ["transaction_item_id"],
    )

    op.create_table(
        "purchase_return_item_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_return_item_id", sa.Uuid(), nullable=False),
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
            name="ck_purchase_return_item_allocations_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_return_item_id"],
            ["purchase_return_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_return_item_id",
            "block_id",
            name="uq_purchase_return_item_allocations_item_block",
        ),
    )
    op.create_index(
        "ix_purchase_return_item_allocations_batch_id",
        "purchase_return_item_allocations",
        ["batch_id"],
    )
    op.create_index(
        "ix_purchase_return_item_allocations_block_id",
        "purchase_return_item_allocations",
        ["block_id"],
    )

    op.create_table(
        "purchase_supplier_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_return_item_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("amount > 0", name="ck_purchase_supplier_refunds_amount_positive"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(
            ["purchase_return_item_id"], ["purchase_return_items.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_supplier_refunds_transaction_id",
        "purchase_supplier_refunds",
        ["transaction_id"],
    )
    op.create_index(
        "ix_purchase_supplier_refunds_return_item_id",
        "purchase_supplier_refunds",
        ["purchase_return_item_id"],
    )

    op.create_table(
        "purchase_replacements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_return_id", sa.Uuid(), nullable=False),
        sa.Column("replacement_date", sa.Date(), nullable=False),
        sa.Column("replacement_time", sa.Time(), nullable=True),
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
        sa.ForeignKeyConstraint(["purchase_return_id"], ["purchase_returns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_replacements_transaction_id",
        "purchase_replacements",
        ["transaction_id"],
    )
    op.create_index(
        "ix_purchase_replacements_purchase_return_id",
        "purchase_replacements",
        ["purchase_return_id"],
    )

    op.create_table(
        "purchase_replacement_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_replacement_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_return_item_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("bonus_quantity", sa.Integer(), nullable=False),
        sa.Column("credit_applied_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_received > 0",
            name="ck_purchase_replacement_items_quantity_positive",
        ),
        sa.CheckConstraint(
            "bonus_quantity >= 0 AND bonus_quantity <= quantity_received",
            name="ck_purchase_replacement_items_bonus_quantity_valid",
        ),
        sa.CheckConstraint(
            "credit_applied_amount >= 0",
            name="ck_purchase_replacement_items_credit_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_replacement_id"],
            ["purchase_replacements.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_return_item_id"], ["purchase_return_items.id"]
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_replacement_items_purchase_return_item_id",
        "purchase_replacement_items",
        ["purchase_return_item_id"],
    )

    op.create_table(
        "purchase_replacement_item_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_replacement_item_id", sa.Uuid(), nullable=False),
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
            name="ck_purchase_replacement_item_allocations_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_replacement_item_id"],
            ["purchase_replacement_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_replacement_item_id",
            "block_id",
            name="uq_purchase_replacement_item_allocations_item_block",
        ),
    )
    op.create_index(
        "ix_purchase_replacement_item_allocations_block_id",
        "purchase_replacement_item_allocations",
        ["block_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_replacement_item_allocations_block_id",
        table_name="purchase_replacement_item_allocations",
    )
    op.drop_table("purchase_replacement_item_allocations")
    op.drop_index(
        "ix_purchase_replacement_items_purchase_return_item_id",
        table_name="purchase_replacement_items",
    )
    op.drop_table("purchase_replacement_items")
    op.drop_index(
        "ix_purchase_replacements_purchase_return_id",
        table_name="purchase_replacements",
    )
    op.drop_index(
        "ix_purchase_replacements_transaction_id",
        table_name="purchase_replacements",
    )
    op.drop_table("purchase_replacements")
    op.drop_index(
        "ix_purchase_supplier_refunds_return_item_id",
        table_name="purchase_supplier_refunds",
    )
    op.drop_index(
        "ix_purchase_supplier_refunds_transaction_id",
        table_name="purchase_supplier_refunds",
    )
    op.drop_table("purchase_supplier_refunds")
    op.drop_index(
        "ix_purchase_return_item_allocations_block_id",
        table_name="purchase_return_item_allocations",
    )
    op.drop_index(
        "ix_purchase_return_item_allocations_batch_id",
        table_name="purchase_return_item_allocations",
    )
    op.drop_table("purchase_return_item_allocations")
    op.drop_index(
        "ix_purchase_return_items_transaction_item_id",
        table_name="purchase_return_items",
    )
    op.drop_index(
        "ix_purchase_return_items_return_id",
        table_name="purchase_return_items",
    )
    op.drop_table("purchase_return_items")
    op.drop_index("ix_purchase_returns_transaction_id", table_name="purchase_returns")
    op.drop_table("purchase_returns")
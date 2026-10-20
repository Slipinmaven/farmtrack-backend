"""add transactions, chicken transaction items, and purchase receipts

Revision ID: 9d31fa6b2c70
Revises: 4a0e6d9e1f2c
Create Date: 2026-10-08 15:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '9d31fa6b2c70'
down_revision: Union[str, Sequence[str], None] = '4a0e6d9e1f2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


transaction_type = postgresql.ENUM(
    "SALE", "PURCHASE", name="transactiontype", create_type=False
)
transaction_status = postgresql.ENUM(
    "COMPLETED", "CANCELLED", name="transactionstatus", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    transaction_type.create(bind, checkfirst=True)
    transaction_status.create(bind, checkfirst=True)

    op.drop_constraint(
        "chicken_batch_initial_quantity_positive",
        "chicken_batches",
        type_="check",
    )
    op.drop_column("chicken_batches", "initial_quantity")

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("transaction_type", transaction_type, nullable=False),
        sa.Column("status", transaction_status, nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_farm_id", "transactions", ["farm_id"])
    op.create_index("ix_transactions_contact_id", "transactions", ["contact_id"])
    op.create_index("ix_transactions_transaction_type", "transactions", ["transaction_type"])
    op.create_index("ix_transactions_status", "transactions", ["status"])
    op.create_index("ix_transactions_transaction_date", "transactions", ["transaction_date"])

    op.create_table(
        "transaction_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("conversion_factor", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_transaction_items_quantity_positive"),
        sa.CheckConstraint("conversion_factor > 0", name="ck_transaction_items_conversion_factor_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_transaction_items_unit_price_non_negative"),
        sa.CheckConstraint("total_amount >= 0", name="ck_transaction_items_total_amount_non_negative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transaction_items_transaction_id", "transaction_items", ["transaction_id"])
    op.create_index("ix_transaction_items_product_id", "transaction_items", ["product_id"])
    op.create_index("ix_transaction_items_unit_id", "transaction_items", ["unit_id"])

    op.create_table(
        "chicken_transaction_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_item_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.ForeignKeyConstraint(["transaction_item_id"], ["transaction_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_item_id"),
    )
    op.create_index("ix_chicken_transaction_items_batch_id", "chicken_transaction_items", ["batch_id"])
    op.create_index("ix_chicken_transaction_items_block_id", "chicken_transaction_items", ["block_id"])

    op.create_table(
        "purchase_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_receipts_transaction_id", "purchase_receipts", ["transaction_id"])
    op.create_index("ix_purchase_receipts_received_date", "purchase_receipts", ["received_date"])

    op.create_table(
        "purchase_receipt_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_receipt_items_quantity_positive"),
        sa.ForeignKeyConstraint(["purchase_receipt_id"], ["purchase_receipts.id"]),
        sa.ForeignKeyConstraint(["transaction_item_id"], ["transaction_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_receipt_items_receipt_id", "purchase_receipt_items", ["purchase_receipt_id"])
    op.create_index("ix_purchase_receipt_items_transaction_item_id", "purchase_receipt_items", ["transaction_item_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_receipt_items_transaction_item_id", table_name="purchase_receipt_items")
    op.drop_index("ix_purchase_receipt_items_receipt_id", table_name="purchase_receipt_items")
    op.drop_table("purchase_receipt_items")

    op.drop_index("ix_purchase_receipts_received_date", table_name="purchase_receipts")
    op.drop_index("ix_purchase_receipts_transaction_id", table_name="purchase_receipts")
    op.drop_table("purchase_receipts")

    op.drop_index("ix_chicken_transaction_items_block_id", table_name="chicken_transaction_items")
    op.drop_index("ix_chicken_transaction_items_batch_id", table_name="chicken_transaction_items")
    op.drop_table("chicken_transaction_items")

    op.drop_index("ix_transaction_items_unit_id", table_name="transaction_items")
    op.drop_index("ix_transaction_items_product_id", table_name="transaction_items")
    op.drop_index("ix_transaction_items_transaction_id", table_name="transaction_items")
    op.drop_table("transaction_items")

    op.drop_index("ix_transactions_transaction_date", table_name="transactions")
    op.drop_index("ix_transactions_status", table_name="transactions")
    op.drop_index("ix_transactions_transaction_type", table_name="transactions")
    op.drop_index("ix_transactions_contact_id", table_name="transactions")
    op.drop_index("ix_transactions_farm_id", table_name="transactions")
    op.drop_table("transactions")

    op.add_column(
        "chicken_batches",
        sa.Column("initial_quantity", sa.Integer(), server_default="1", nullable=False),
    )
    op.alter_column("chicken_batches", "initial_quantity", server_default=None)
    op.create_check_constraint(
        "chicken_batch_initial_quantity_positive",
        "chicken_batches",
        "initial_quantity > 0",
    )

    transaction_status.drop(op.get_bind(), checkfirst=True)
    transaction_type.drop(op.get_bind(), checkfirst=True)

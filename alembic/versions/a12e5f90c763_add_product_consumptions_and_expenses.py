"""add product consumptions and expenses

Revision ID: a12e5f90c763
Revises: 4c81d0e7a2b9
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a12e5f90c763"
down_revision: Union[str, Sequence[str], None] = "4c81d0e7a2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

expense_category = postgresql.ENUM(
    "FEED",
    "MEDICATION",
    "VETERINARY",
    "LABOR",
    "UTILITIES",
    "TRANSPORT",
    "REPAIRS",
    "RENT",
    "EQUIPMENT",
    "PACKAGING",
    "OTHER",
    name="expense_category",
    create_type=False,
)

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
    expense_category.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'PRODUCT_CONSUMPTION_RECORDED'"
    )
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'EXPENSE_RECORDED'")
    op.execute(
        "ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'PRODUCT_CONSUMPTION'"
    )
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'EXPENSE'")

    op.create_table(
        "product_consumptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("conversion_factor", sa.Numeric(12, 3), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("consumption_date", sa.Date(), nullable=False),
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
            "quantity > 0",
            name="ck_product_consumptions_quantity_positive",
        ),
        sa.CheckConstraint(
            "conversion_factor > 0",
            name="ck_product_consumptions_conversion_factor_positive",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_consumptions_farm_id",
        "product_consumptions",
        ["farm_id"],
    )
    op.create_index(
        "ix_product_consumptions_product_id",
        "product_consumptions",
        ["product_id"],
    )
    op.create_index(
        "ix_product_consumptions_unit_id",
        "product_consumptions",
        ["unit_id"],
    )
    op.create_index(
        "ix_product_consumptions_block_id",
        "product_consumptions",
        ["block_id"],
    )
    op.create_index(
        "ix_product_consumptions_batch_id",
        "product_consumptions",
        ["batch_id"],
    )
    op.create_index(
        "ix_product_consumptions_consumption_date",
        "product_consumptions",
        ["consumption_date"],
    )

    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("category", expense_category, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("payment_method", payment_method, nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
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
        sa.CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expenses_farm_id", "expenses", ["farm_id"])
    op.create_index("ix_expenses_category", "expenses", ["category"])
    op.create_index("ix_expenses_expense_date", "expenses", ["expense_date"])
    op.create_index("ix_expenses_contact_id", "expenses", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_expenses_contact_id", table_name="expenses")
    op.drop_index("ix_expenses_expense_date", table_name="expenses")
    op.drop_index("ix_expenses_category", table_name="expenses")
    op.drop_index("ix_expenses_farm_id", table_name="expenses")
    op.drop_table("expenses")

    op.drop_index(
        "ix_product_consumptions_consumption_date",
        table_name="product_consumptions",
    )
    op.drop_index(
        "ix_product_consumptions_batch_id",
        table_name="product_consumptions",
    )
    op.drop_index(
        "ix_product_consumptions_block_id",
        table_name="product_consumptions",
    )
    op.drop_index(
        "ix_product_consumptions_unit_id",
        table_name="product_consumptions",
    )
    op.drop_index(
        "ix_product_consumptions_product_id",
        table_name="product_consumptions",
    )
    op.drop_index(
        "ix_product_consumptions_farm_id",
        table_name="product_consumptions",
    )
    op.drop_table("product_consumptions")
    expense_category.drop(op.get_bind(), checkfirst=True)
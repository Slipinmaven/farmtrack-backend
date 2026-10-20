"""expand expense management

Revision ID: bb19d4e5a6c7
Revises: 8c12a0f4b7d9
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "bb19d4e5a6c7"
down_revision: Union[str, Sequence[str], None] = "8c12a0f4b7d9"
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

categories = (
    ("feed_and_nutrition", "Feed and nutrition"),
    ("medication_veterinary", "Medication and veterinary"),
    ("labour", "Labour"),
    ("utilities", "Utilities"),
    ("transport", "Transport"),
    ("repairs_maintenance", "Repairs and maintenance"),
    ("equipment", "Equipment"),
    ("housing_facilities", "Housing and facilities"),
    ("packaging", "Packaging"),
    ("administration", "Administration"),
    ("other", "Other"),
)


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("farm_id", "key", name="uq_expense_categories_farm_key"),
    )
    op.create_index(
        "ix_expense_categories_farm_id",
        "expense_categories",
        ["farm_id"],
    )

    category_names = dict(categories)
    op.execute(
        sa.text(
            """
            INSERT INTO expense_categories
                (id, farm_id, key, name, is_default, is_active)
            SELECT gen_random_uuid(), farms.id, category.key, category.name, TRUE, TRUE
            FROM farms
            CROSS JOIN (
                VALUES
                    ('feed_and_nutrition', :feed),
                    ('medication_veterinary', :medication),
                    ('labour', :labour),
                    ('utilities', :utilities),
                    ('transport', :transport),
                    ('repairs_maintenance', :repairs),
                    ('equipment', :equipment),
                    ('housing_facilities', :housing),
                    ('packaging', :packaging),
                    ('administration', :administration),
                    ('other', :other)
            ) AS category(key, name)
            """
        ).bindparams(
            feed=category_names["feed_and_nutrition"],
            medication=category_names["medication_veterinary"],
            labour=category_names["labour"],
            utilities=category_names["utilities"],
            transport=category_names["transport"],
            repairs=category_names["repairs_maintenance"],
            equipment=category_names["equipment"],
            housing=category_names["housing_facilities"],
            packaging=category_names["packaging"],
            administration=category_names["administration"],
            other=category_names["other"],
        )
    )

    op.add_column("expenses", sa.Column("name", sa.String(length=120), nullable=True))
    op.add_column("expenses", sa.Column("block_id", sa.Uuid(), nullable=True))
    op.add_column(
        "expenses",
        sa.Column("receipt_reference", sa.String(length=500), nullable=True),
    )
    op.add_column("expenses", sa.Column("canceled_at", sa.DateTime(timezone=True)))
    op.add_column("expenses", sa.Column("cancellation_reason", sa.Text()))
    op.create_foreign_key(
        "fk_expenses_block_id_blocks",
        "expenses",
        "blocks",
        ["block_id"],
        ["id"],
    )
    op.create_index("ix_expenses_block_id", "expenses", ["block_id"])

    op.execute(
        """
        UPDATE expenses
        SET name = CASE category::text
            WHEN 'FEED' THEN 'Feed expense'
            WHEN 'MEDICATION' THEN 'Medication expense'
            WHEN 'VETERINARY' THEN 'Veterinary expense'
            WHEN 'LABOR' THEN 'Labour expense'
            WHEN 'UTILITIES' THEN 'Utilities expense'
            WHEN 'TRANSPORT' THEN 'Transport expense'
            WHEN 'REPAIRS' THEN 'Repairs and maintenance'
            WHEN 'RENT' THEN 'Housing expense'
            WHEN 'EQUIPMENT' THEN 'Equipment expense'
            WHEN 'PACKAGING' THEN 'Packaging expense'
            ELSE 'Farm expense'
        END
        """
    )
    op.alter_column("expenses", "name", nullable=False)
    op.drop_index("ix_expenses_category", table_name="expenses")
    op.alter_column(
        "expenses",
        "category",
        existing_type=postgresql.ENUM(name="expense_category"),
        type_=sa.String(length=80),
        postgresql_using="""
            CASE category::text
                WHEN 'FEED' THEN 'feed_and_nutrition'
                WHEN 'MEDICATION' THEN 'medication_veterinary'
                WHEN 'VETERINARY' THEN 'medication_veterinary'
                WHEN 'LABOR' THEN 'labour'
                WHEN 'UTILITIES' THEN 'utilities'
                WHEN 'TRANSPORT' THEN 'transport'
                WHEN 'REPAIRS' THEN 'repairs_maintenance'
                WHEN 'RENT' THEN 'housing_facilities'
                WHEN 'EQUIPMENT' THEN 'equipment'
                WHEN 'PACKAGING' THEN 'packaging'
                ELSE 'other'
            END
        """,
    )
    op.create_index("ix_expenses_category", "expenses", ["category"])

    op.create_table(
        "expense_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("expense_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="payment"),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", payment_method, nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_expense_payments_amount_positive"),
        sa.CheckConstraint(
            "kind IN ('payment', 'refund')",
            name="ck_expense_payments_kind_valid",
        ),
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expenses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_expense_payments_expense_id",
        "expense_payments",
        ["expense_id"],
    )
    op.execute(
        """
        INSERT INTO expense_payments
            (id, expense_id, amount, payment_date, payment_method, reference_number)
        SELECT gen_random_uuid(), id, amount, expense_date, payment_method,
               reference_number
        FROM expenses
        """
    )


def downgrade() -> None:
    op.drop_index("ix_expense_payments_expense_id", table_name="expense_payments")
    op.drop_table("expense_payments")
    op.drop_index("ix_expenses_block_id", table_name="expenses")
    op.drop_constraint("fk_expenses_block_id_blocks", "expenses", type_="foreignkey")
    op.drop_column("expenses", "cancellation_reason")
    op.drop_column("expenses", "canceled_at")
    op.drop_column("expenses", "receipt_reference")
    op.drop_column("expenses", "block_id")
    op.drop_column("expenses", "name")
    op.drop_index("ix_expenses_category", table_name="expenses")
    op.alter_column(
        "expenses",
        "category",
        existing_type=sa.String(length=80),
        type_=postgresql.ENUM(
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
        ),
        postgresql_using="""
            CASE category
                WHEN 'feed_and_nutrition' THEN 'FEED'
                WHEN 'medication_veterinary' THEN 'MEDICATION'
                WHEN 'labour' THEN 'LABOR'
                WHEN 'utilities' THEN 'UTILITIES'
                WHEN 'transport' THEN 'TRANSPORT'
                WHEN 'repairs_maintenance' THEN 'REPAIRS'
                WHEN 'equipment' THEN 'EQUIPMENT'
                WHEN 'housing_facilities' THEN 'RENT'
                WHEN 'packaging' THEN 'PACKAGING'
                ELSE 'OTHER'
            END
        """,
    )
    op.create_index("ix_expenses_category", "expenses", ["category"])
    op.drop_index(
        "ix_expense_categories_farm_id",
        table_name="expense_categories",
    )
    op.drop_table("expense_categories")

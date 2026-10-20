"""add chicken purchase discounts

Revision ID: e1d14c4c76ab
Revises: d4a82e6c901f
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1d14c4c76ab"
down_revision: Union[str, Sequence[str], None] = "d4a82e6c901f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("discount_type", sa.String(length=12), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "discount_value",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "discount_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )
    op.add_column(
        "transactions",
        sa.Column("discount_reason", sa.String(length=200), nullable=True),
    )
    op.create_check_constraint(
        "ck_transactions_discount_value_non_negative",
        "transactions",
        "discount_value >= 0",
    )
    op.create_check_constraint(
        "ck_transactions_discount_amount_non_negative",
        "transactions",
        "discount_amount >= 0",
    )
    op.create_check_constraint(
        "ck_transactions_discount_type_valid",
        "transactions",
        "discount_type IS NULL OR discount_type IN ('fixed', 'percentage')",
    )
    op.create_check_constraint(
        "ck_transactions_percentage_discount_maximum",
        "transactions",
        "discount_type != 'percentage' OR discount_value <= 100",
    )
    op.create_check_constraint(
        "ck_transactions_discount_terms_consistent",
        "transactions",
        "discount_type IS NOT NULL OR discount_value = 0",
    )
    op.add_column(
        "transaction_items",
        sa.Column(
            "subtotal_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )
    op.add_column(
        "transaction_items",
        sa.Column(
            "discount_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
    )
    op.execute(
        "UPDATE transaction_items SET subtotal_amount = total_amount, discount_amount = 0.00"
    )
    op.create_check_constraint(
        "ck_transaction_items_discount_amount_valid",
        "transaction_items",
        "subtotal_amount >= 0 AND discount_amount >= 0 AND discount_amount <= subtotal_amount",
    )
    op.create_check_constraint(
        "ck_transaction_items_total_matches_discounted_subtotal",
        "transaction_items",
        "total_amount = subtotal_amount - discount_amount",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_transaction_items_total_matches_discounted_subtotal",
        "transaction_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_transaction_items_discount_amount_valid",
        "transaction_items",
        type_="check",
    )
    op.drop_column("transaction_items", "discount_amount")
    op.drop_column("transaction_items", "subtotal_amount")
    for constraint in (
        "ck_transactions_discount_terms_consistent",
        "ck_transactions_percentage_discount_maximum",
        "ck_transactions_discount_type_valid",
        "ck_transactions_discount_amount_non_negative",
        "ck_transactions_discount_value_non_negative",
    ):
        op.drop_constraint(constraint, "transactions", type_="check")
    for column in (
        "discount_reason",
        "discount_amount",
        "discount_value",
        "discount_type",
    ):
        op.drop_column("transactions", column)
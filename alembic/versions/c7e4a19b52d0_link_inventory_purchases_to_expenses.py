"""link inventory purchase transactions to expenses

Revision ID: c7e4a19b52d0
Revises: bb19d4e5a6c7
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e4a19b52d0"
down_revision: Union[str, Sequence[str], None] = "bb19d4e5a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column("purchase_transaction_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_expenses_purchase_transaction_id_transactions",
        "expenses",
        "transactions",
        ["purchase_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_expenses_purchase_transaction_id",
        "expenses",
        ["purchase_transaction_id"],
    )
    op.add_column(
        "expense_payments",
        sa.Column("purchase_payment_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_expense_payments_purchase_payment_id_transaction_payments",
        "expense_payments",
        "transaction_payments",
        ["purchase_payment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_expense_payments_purchase_payment_id",
        "expense_payments",
        ["purchase_payment_id"],
    )
    op.execute(
        sa.text(
            """
            WITH eligible_purchase_items AS (
                SELECT
                    t.id AS transaction_id,
                    t.farm_id,
                    t.contact_id,
                    t.transaction_date,
                    t.reference_number,
                    t.notes AS transaction_notes,
                    COUNT(DISTINCT p.product_type) AS product_type_count,
                    MIN(p.product_type::text) AS product_type,
                    SUM(ti.total_amount) AS expense_amount,
                    STRING_AGG(DISTINCT p.name, ', ' ORDER BY p.name) AS product_names
                FROM transactions AS t
                JOIN transaction_items AS ti ON ti.transaction_id = t.id
                JOIN products AS p ON p.id = ti.product_id
                WHERE t.transaction_type = 'PURCHASE'
                  AND t.status = 'COMPLETED'
                  AND p.product_type NOT IN ('CHICKENS', 'EGGS')
                GROUP BY
                    t.id,
                    t.farm_id,
                    t.contact_id,
                    t.transaction_date,
                    t.reference_number,
                    t.notes
            ),
            categorized_purchases AS (
                SELECT
                    *,
                    CASE
                        WHEN product_type_count > 1 THEN 'other'
                        WHEN product_type = 'FEED' THEN 'feed_and_nutrition'
                        WHEN product_type = 'MEDICATION' THEN 'medication_veterinary'
                        WHEN product_type = 'EQUIPMENT' THEN 'equipment'
                        ELSE 'other'
                    END AS category
                FROM eligible_purchase_items
                WHERE expense_amount > 0
            )
            INSERT INTO expenses (
                id,
                farm_id,
                name,
                category,
                amount,
                expense_date,
                contact_id,
                payment_method,
                reference_number,
                notes,
                purchase_transaction_id,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                cp.farm_id,
                'Inventory purchase ' || COALESCE(cp.reference_number, cp.transaction_id::text),
                cp.category,
                cp.expense_amount,
                cp.transaction_date,
                cp.contact_id,
                COALESCE(
                    (
                        SELECT tp.payment_method
                        FROM transaction_payments AS tp
                        WHERE tp.transaction_id = cp.transaction_id
                        ORDER BY tp.payment_date DESC, tp.payment_time DESC NULLS LAST, tp.id DESC
                        LIMIT 1
                    ),
                    'CASH'::paymentmethod
                ),
                (
                    SELECT tp.reference_number
                    FROM transaction_payments AS tp
                    WHERE tp.transaction_id = cp.transaction_id
                    ORDER BY tp.payment_date DESC, tp.payment_time DESC NULLS LAST, tp.id DESC
                    LIMIT 1
                ),
                concat_ws(
                    E'\\n',
                    NULLIF(cp.transaction_notes, ''),
                    'Purchased products: ' || cp.product_names
                ),
                cp.transaction_id,
                now(),
                now()
            FROM categorized_purchases AS cp
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH purchase_payments AS (
                SELECT
                    e.id AS expense_id,
                    e.amount AS expense_amount,
                    tp.id AS payment_id,
                    tp.amount AS payment_amount,
                    tp.payment_date,
                    tp.payment_method,
                    tp.reference_number,
                    tp.created_at,
                    COALESCE(
                        SUM(tp.amount) OVER (
                            PARTITION BY tp.transaction_id
                            ORDER BY tp.payment_date, tp.payment_time, tp.created_at, tp.id
                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                        ),
                        0
                    ) AS paid_before
                FROM expenses AS e
                JOIN transaction_payments AS tp
                  ON tp.transaction_id = e.purchase_transaction_id
                WHERE e.purchase_transaction_id IS NOT NULL
            )
            INSERT INTO expense_payments (
                id,
                expense_id,
                purchase_payment_id,
                kind,
                amount,
                payment_date,
                payment_method,
                reference_number,
                created_at
            )
            SELECT
                gen_random_uuid(),
                pp.expense_id,
                pp.payment_id,
                'payment',
                LEAST(pp.payment_amount, GREATEST(pp.expense_amount - pp.paid_before, 0)),
                pp.payment_date,
                pp.payment_method,
                pp.reference_number,
                pp.created_at
            FROM purchase_payments AS pp
            WHERE LEAST(pp.payment_amount, GREATEST(pp.expense_amount - pp.paid_before, 0)) > 0
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM expense_payments WHERE purchase_payment_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM expenses WHERE purchase_transaction_id IS NOT NULL"
        )
    )
    op.drop_constraint(
        "uq_expense_payments_purchase_payment_id",
        "expense_payments",
        type_="unique",
    )
    op.drop_constraint(
        "fk_expense_payments_purchase_payment_id_transaction_payments",
        "expense_payments",
        type_="foreignkey",
    )
    op.drop_column("expense_payments", "purchase_payment_id")
    op.drop_constraint(
        "uq_expenses_purchase_transaction_id",
        "expenses",
        type_="unique",
    )
    op.drop_constraint(
        "fk_expenses_purchase_transaction_id_transactions",
        "expenses",
        type_="foreignkey",
    )
    op.drop_column("expenses", "purchase_transaction_id")

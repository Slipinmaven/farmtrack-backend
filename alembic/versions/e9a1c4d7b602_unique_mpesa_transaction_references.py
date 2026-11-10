"""Reconcile duplicate M-Pesa references and prevent future duplicates."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a1c4d7b602"
down_revision: Union[str, Sequence[str], None] = "d6f1a9c2b483"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked_references AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY lower(trim(reference_number))
                        ORDER BY created_at, id
                    ) AS duplicate_number
                FROM transaction_payments
                WHERE payment_method = 'MPESA'
                  AND reference_number IS NOT NULL
                  AND btrim(reference_number) <> ''
            )
            UPDATE transaction_payments AS payment
            SET reference_number =
                left(
                    btrim(payment.reference_number),
                    100 - length('-LEGACY-' || payment.id::text)
                ) || '-LEGACY-' || payment.id::text
            FROM ranked_references
            WHERE payment.id = ranked_references.id
              AND ranked_references.duplicate_number > 1;
            """
        )
    )
    op.create_index(
        "uq_transaction_payments_mpesa_reference",
        "transaction_payments",
        [sa.text("lower(trim(reference_number))")],
        unique=True,
        postgresql_where=sa.text(
            "payment_method = 'MPESA' AND reference_number IS NOT NULL "
            "AND btrim(reference_number) <> ''"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_transaction_payments_mpesa_reference",
        table_name="transaction_payments",
    )

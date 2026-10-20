"""Add atomic daily transaction reference counters."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8c57a21b406"
down_revision: Union[str, Sequence[str], None] = "da1c9e32b74f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_reference_counters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("reference_type", sa.String(length=20), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "last_number >= 0",
            name="ck_transaction_reference_counter_nonnegative",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "farm_id",
            "reference_type",
            "reference_date",
            name="uq_transaction_reference_counters_scope",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO transaction_reference_counters
                (id, farm_id, reference_type, reference_date, last_number)
            SELECT md5(
                       farm_id::text || ':' ||
                       CASE substring(reference_number FROM 1 FOR 3)
                           WHEN 'SAL' THEN 'sale'
                           ELSE 'purchase'
                       END || ':' ||
                       to_date(substring(reference_number FROM 5 FOR 8), 'YYYYMMDD')::text
                   )::uuid,
                   farm_id,
                   CASE substring(reference_number FROM 1 FOR 3)
                       WHEN 'SAL' THEN 'sale'
                       ELSE 'purchase'
                   END,
                   to_date(substring(reference_number FROM 5 FOR 8), 'YYYYMMDD'),
                   max(substring(reference_number FROM 14)::integer)
            FROM transactions
            WHERE reference_number ~ '^(SAL|PUR)-[0-9]{8}-[0-9]{4,}$'
            GROUP BY farm_id,
                     substring(reference_number FROM 1 FOR 3),
                     to_date(substring(reference_number FROM 5 FOR 8), 'YYYYMMDD')
            """
        )
    )
    op.create_unique_constraint(
        "uq_transactions_farm_reference_number",
        "transactions",
        ["farm_id", "reference_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_transactions_farm_reference_number",
        "transactions",
        type_="unique",
    )
    op.drop_table("transaction_reference_counters")
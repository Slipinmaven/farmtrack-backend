"""Add atomic daily chicken batch name counters."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a741b62c3e90"
down_revision: Union[str, Sequence[str], None] = "f8c57a21b406"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chicken_batch_name_counters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("batch_date", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "farm_id",
            "batch_date",
            name="uq_chicken_batch_name_counters_farm_date",
        ),
    )
    op.execute(
        sa.text(
            """
            WITH parsed AS (
                SELECT farm_id,
                       to_date(
                           substring(name FROM '^([0-9]{4} [A-Za-z]+ [0-9]{1,2}) Batch'),
                           'YYYY Month DD'
                       ) AS batch_date,
                       substring(name FROM 'Batch ([0-9]+)$')::integer AS batch_number
                FROM chicken_batches
                WHERE name ~ '^[0-9]{4} [A-Za-z]+ [0-9]{1,2} Batch [0-9]+$'
            )
            INSERT INTO chicken_batch_name_counters
                (id, farm_id, batch_date, last_number)
            SELECT md5(farm_id::text || ':' || batch_date::text)::uuid,
                   farm_id,
                   batch_date,
                   max(batch_number)
            FROM parsed
            GROUP BY farm_id, batch_date
            """
        )
    )


def downgrade() -> None:
    op.drop_table("chicken_batch_name_counters")
"""confirm zero egg production cost for report periods

Revision ID: d6f1a9c2b483
Revises: c8d4e2f6a190
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6f1a9c2b483"
down_revision: Union[str, Sequence[str], None] = "c8d4e2f6a190"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "egg_production_cost_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_date <= to_date",
            name="ck_egg_prod_cost_confirmation_dates",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "farm_id",
            "from_date",
            "to_date",
            name="uq_egg_prod_cost_confirmation_period",
        ),
    )
    op.create_index(
        "ix_egg_prod_cost_confirmation_farm_period",
        "egg_production_cost_confirmations",
        ["farm_id", "from_date", "to_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_egg_prod_cost_confirmation_farm_period",
        table_name="egg_production_cost_confirmations",
    )
    op.drop_table("egg_production_cost_confirmations")

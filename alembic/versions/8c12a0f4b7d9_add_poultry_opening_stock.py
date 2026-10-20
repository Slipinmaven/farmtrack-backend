"""add one-time poultry opening stock records

Revision ID: 8c12a0f4b7d9
Revises: 5c26a1d9e704
Create Date: 2026-10-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c12a0f4b7d9"
down_revision: Union[str, Sequence[str], None] = "5c26a1d9e704"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE activitytype "
        "ADD VALUE IF NOT EXISTS 'INVENTORY_OPENING_STOCK_RECORDED'"
    )
    op.execute(
        "ALTER TYPE activityentitytype "
        "ADD VALUE IF NOT EXISTS 'INVENTORY_OPENING_SETUP'"
    )
    op.add_column(
        "chicken_batches",
        sa.Column(
            "is_opening_stock",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "inventory_opening_setups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("species", sa.String(length=16), nullable=False),
        sa.Column("setup_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "species IN ('chickens', 'eggs')",
            name="ck_inventory_opening_species",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "farm_id",
            "species",
            name="uq_inventory_opening_farm_species",
        ),
    )
    op.add_column(
        "egg_collections",
        sa.Column(
            "entry_type",
            sa.String(length=24),
            server_default="collection",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_egg_collections_entry_type",
        "egg_collections",
        "entry_type IN ('collection', 'opening_stock')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_egg_collections_entry_type",
        "egg_collections",
        type_="check",
    )
    op.drop_column("egg_collections", "entry_type")
    op.drop_table("inventory_opening_setups")
    op.drop_column("chicken_batches", "is_opening_stock")

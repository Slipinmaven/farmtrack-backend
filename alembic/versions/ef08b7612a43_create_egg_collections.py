"""create egg collections

Revision ID: ef08b7612a43
Revises: b6f2a94d18ce
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ef08b7612a43"
down_revision: Union[str, Sequence[str], None] = "b6f2a94d18ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'EGG_COLLECTION_RECORDED'")
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'EGG_COLLECTION'")
    op.create_table(
        "egg_collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("conversion_factor", sa.Numeric(12, 3), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
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
            name="ck_egg_collections_quantity_positive",
        ),
        sa.CheckConstraint(
            "conversion_factor > 0",
            name="ck_egg_collections_conversion_factor_positive",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_egg_collections_farm_id", "egg_collections", ["farm_id"])
    op.create_index("ix_egg_collections_product_id", "egg_collections", ["product_id"])
    op.create_index("ix_egg_collections_block_id", "egg_collections", ["block_id"])
    op.create_index("ix_egg_collections_unit_id", "egg_collections", ["unit_id"])
    op.create_index(
        "ix_egg_collections_collected_at",
        "egg_collections",
        ["collected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_egg_collections_collected_at", table_name="egg_collections")
    op.drop_index("ix_egg_collections_unit_id", table_name="egg_collections")
    op.drop_index("ix_egg_collections_block_id", table_name="egg_collections")
    op.drop_index("ix_egg_collections_product_id", table_name="egg_collections")
    op.drop_index("ix_egg_collections_farm_id", table_name="egg_collections")
    op.drop_table("egg_collections")
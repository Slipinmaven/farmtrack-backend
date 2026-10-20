"""create chicken movements ledger

Revision ID: 9a54ce67d2f1
Revises: c349a17d560e
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a54ce67d2f1"
down_revision: Union[str, Sequence[str], None] = "c349a17d560e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'CHICKEN_MOVEMENT_CREATED'")
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'CHICKEN_MOVEMENT'")
    op.create_table(
        "chicken_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("from_block_id", sa.Uuid(), nullable=False),
        sa.Column("to_block_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=True),
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
            name="ck_chicken_movements_quantity_positive",
        ),
        sa.CheckConstraint(
            "from_block_id <> to_block_id",
            name="ck_chicken_movements_blocks_different",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.ForeignKeyConstraint(["from_block_id"], ["blocks.id"]),
        sa.ForeignKeyConstraint(["to_block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chicken_movements_farm_id",
        "chicken_movements",
        ["farm_id"],
    )
    op.create_index(
        "ix_chicken_movements_batch_id",
        "chicken_movements",
        ["batch_id"],
    )
    op.create_index(
        "ix_chicken_movements_from_block_id",
        "chicken_movements",
        ["from_block_id"],
    )
    op.create_index(
        "ix_chicken_movements_to_block_id",
        "chicken_movements",
        ["to_block_id"],
    )
    op.create_index(
        "ix_chicken_movements_movement_date",
        "chicken_movements",
        ["movement_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_chicken_movements_movement_date", table_name="chicken_movements")
    op.drop_index("ix_chicken_movements_to_block_id", table_name="chicken_movements")
    op.drop_index("ix_chicken_movements_from_block_id", table_name="chicken_movements")
    op.drop_index("ix_chicken_movements_batch_id", table_name="chicken_movements")
    op.drop_index("ix_chicken_movements_farm_id", table_name="chicken_movements")
    op.drop_table("chicken_movements")
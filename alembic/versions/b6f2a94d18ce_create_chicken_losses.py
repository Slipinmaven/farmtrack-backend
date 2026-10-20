"""create chicken losses ledger

Revision ID: b6f2a94d18ce
Revises: 9a54ce67d2f1
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b6f2a94d18ce"
down_revision: Union[str, Sequence[str], None] = "9a54ce67d2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

chicken_loss_reason = postgresql.ENUM(
    "DISEASE",
    "NATURAL_DEATH",
    "PREDATOR",
    "INJURY",
    "ACCIDENT",
    "CULLING",
    "MISSING",
    "OTHER",
    name="chicken_loss_reason",
    create_type=False,
)


def upgrade() -> None:
    chicken_loss_reason.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'CHICKEN_LOSS_RECORDED'")
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'CHICKEN_LOSS'")

    op.create_table(
        "chicken_losses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("loss_date", sa.Date(), nullable=False),
        sa.Column("reason", chicken_loss_reason, nullable=False),
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
            name="ck_chicken_losses_quantity_positive",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["chicken_batches.id"]),
        sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chicken_losses_farm_id", "chicken_losses", ["farm_id"])
    op.create_index("ix_chicken_losses_batch_id", "chicken_losses", ["batch_id"])
    op.create_index("ix_chicken_losses_block_id", "chicken_losses", ["block_id"])
    op.create_index("ix_chicken_losses_loss_date", "chicken_losses", ["loss_date"])


def downgrade() -> None:
    op.drop_index("ix_chicken_losses_loss_date", table_name="chicken_losses")
    op.drop_index("ix_chicken_losses_block_id", table_name="chicken_losses")
    op.drop_index("ix_chicken_losses_batch_id", table_name="chicken_losses")
    op.drop_index("ix_chicken_losses_farm_id", table_name="chicken_losses")
    op.drop_table("chicken_losses")
    chicken_loss_reason.drop(op.get_bind(), checkfirst=True)
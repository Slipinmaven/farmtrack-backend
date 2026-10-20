"""create egg losses ledger

Revision ID: 4c81d0e7a2b9
Revises: ef08b7612a43
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4c81d0e7a2b9"
down_revision: Union[str, Sequence[str], None] = "ef08b7612a43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

egg_loss_reason = postgresql.ENUM(
    "BROKEN",
    "SPOILED",
    "CONTAMINATED",
    "DAMAGED",
    "DISCARDED",
    "OTHER",
    name="egg_loss_reason",
    create_type=False,
)


def upgrade() -> None:
    egg_loss_reason.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'EGG_LOSS_RECORDED'")
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'EGG_LOSS'")

    op.create_table(
        "egg_losses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("conversion_factor", sa.Numeric(12, 3), nullable=False),
        sa.Column("loss_date", sa.Date(), nullable=False),
        sa.Column("reason", egg_loss_reason, nullable=False),
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
        sa.CheckConstraint("quantity > 0", name="ck_egg_losses_quantity_positive"),
        sa.CheckConstraint(
            "conversion_factor > 0",
            name="ck_egg_losses_conversion_factor_positive",
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_egg_losses_farm_id", "egg_losses", ["farm_id"])
    op.create_index("ix_egg_losses_product_id", "egg_losses", ["product_id"])
    op.create_index("ix_egg_losses_unit_id", "egg_losses", ["unit_id"])
    op.create_index("ix_egg_losses_loss_date", "egg_losses", ["loss_date"])
    op.create_index("ix_egg_losses_reason", "egg_losses", ["reason"])


def downgrade() -> None:
    op.drop_index("ix_egg_losses_reason", table_name="egg_losses")
    op.drop_index("ix_egg_losses_loss_date", table_name="egg_losses")
    op.drop_index("ix_egg_losses_unit_id", table_name="egg_losses")
    op.drop_index("ix_egg_losses_product_id", table_name="egg_losses")
    op.drop_index("ix_egg_losses_farm_id", table_name="egg_losses")
    op.drop_table("egg_losses")
    egg_loss_reason.drop(op.get_bind(), checkfirst=True)
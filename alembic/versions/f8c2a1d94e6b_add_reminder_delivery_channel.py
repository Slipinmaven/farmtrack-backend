"""add reminder delivery channel

Revision ID: f8c2a1d94e6b
Revises: e1d14c4c76ab
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8c2a1d94e6b"
down_revision: Union[str, Sequence[str], None] = "e1d14c4c76ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column(
            "delivery_channel",
            sa.String(length=10),
            nullable=False,
            server_default="in_app",
        ),
    )
    op.add_column(
        "reminders",
        sa.Column("expo_push_token", sa.String(length=255), nullable=True),
    )
    op.create_check_constraint(
        "ck_reminders_delivery_channel",
        "reminders",
        "delivery_channel IN ('in_app', 'push') AND "
        "(delivery_channel != 'push' OR expo_push_token IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_reminders_delivery_channel",
        "reminders",
        type_="check",
    )
    op.drop_column("reminders", "expo_push_token")
    op.drop_column("reminders", "delivery_channel")
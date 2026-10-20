"""add notification-created activity type

Revision ID: 2a7c9d4e6f10
Revises: f16a4d82c730
Create Date: 2026-10-18

"""
from typing import Sequence, Union

from alembic import op


revision: str = "2a7c9d4e6f10"
down_revision: Union[str, Sequence[str], None] = "f16a4d82c730"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE activitytype "
        "ADD VALUE IF NOT EXISTS 'NOTIFICATION_CREATED'"
    )


def downgrade() -> None:
    # Keep the enum value so existing activity rows remain valid.
    pass

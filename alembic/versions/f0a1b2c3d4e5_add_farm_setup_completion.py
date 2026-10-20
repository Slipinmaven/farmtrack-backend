"""Add persisted farm setup completion state.

Revision ID: f0a1b2c3d4e5
Revises: e4b9f61d27ac
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e4b9f61d27ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "farms",
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE farms SET setup_completed_at = now()")


def downgrade() -> None:
    op.drop_column("farms", "setup_completed_at")

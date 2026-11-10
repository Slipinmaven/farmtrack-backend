"""Require a separate password for release downloads.

Revision ID: a7c91d4e2f63
Revises: e4b7c19a2d63
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c91d4e2f63"
down_revision: Union[str, Sequence[str], None] = "e4b7c19a2d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "download_tokens",
        sa.Column("password_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE download_tokens "
        "SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP), "
        "password_hash = '0000000000000000000000000000000000000000000000000000000000000000'"
    )
    op.alter_column(
        "download_tokens",
        "password_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("download_tokens", "password_hash")

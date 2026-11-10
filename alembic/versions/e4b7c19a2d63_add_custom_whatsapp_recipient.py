"""Allow release invitations to target a custom WhatsApp phone number.

Revision ID: e4b7c19a2d63
Revises: d934a8f27b10
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b7c19a2d63"
down_revision: Union[str, Sequence[str], None] = "d934a8f27b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "download_tokens",
        "recipient_email",
        existing_type=sa.String(length=320),
        nullable=True,
    )
    op.add_column(
        "download_tokens",
        sa.Column("recipient_phone", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE download_tokens SET recipient_email = 'unknown@invalid.local' "
        "WHERE recipient_email IS NULL"
    )
    op.drop_column("download_tokens", "recipient_phone")
    op.alter_column(
        "download_tokens",
        "recipient_email",
        existing_type=sa.String(length=320),
        nullable=False,
    )

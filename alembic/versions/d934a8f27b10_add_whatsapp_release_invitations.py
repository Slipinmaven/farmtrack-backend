"""Support prepared WhatsApp release invitations.

Revision ID: d934a8f27b10
Revises: c6d9a1f4b827
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d934a8f27b10"
down_revision: Union[str, Sequence[str], None] = "c6d9a1f4b827"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "download_tokens",
        sa.Column(
            "delivery_channel",
            sa.String(length=20),
            server_default="email",
            nullable=False,
        ),
    )
    op.drop_constraint(
        "check_download_tokens_delivery_status",
        "download_tokens",
        type_="check",
    )
    op.create_check_constraint(
        "check_download_tokens_delivery_status",
        "download_tokens",
        "delivery_status IN ('pending', 'sent', 'failed', 'prepared')",
    )
    op.create_check_constraint(
        "check_download_tokens_delivery_channel",
        "download_tokens",
        "delivery_channel IN ('email', 'whatsapp', 'both')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE download_tokens SET delivery_status = 'sent' "
        "WHERE delivery_status = 'prepared'"
    )
    op.drop_constraint(
        "check_download_tokens_delivery_channel",
        "download_tokens",
        type_="check",
    )
    op.drop_constraint(
        "check_download_tokens_delivery_status",
        "download_tokens",
        type_="check",
    )
    op.create_check_constraint(
        "check_download_tokens_delivery_status",
        "download_tokens",
        "delivery_status IN ('pending', 'sent', 'failed')",
    )
    op.drop_column("download_tokens", "delivery_channel")

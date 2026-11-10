"""Track farm invitation email delivery.

Revision ID: b7d2c8a4e901
Revises: a6c91e02d4f7
Create Date: 2026-10-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b7d2c8a4e901"
down_revision: Union[str, Sequence[str], None] = "a6c91e02d4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "farm_memberships",
        sa.Column(
            "invitation_email_status",
            sa.String(length=20),
            server_default="not_configured",
            nullable=False,
        ),
    )
    op.add_column(
        "farm_memberships",
        sa.Column("invitation_email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "check_farm_memberships_invitation_email_status",
        "farm_memberships",
        "invitation_email_status IN "
        "('not_configured', 'queued', 'sent', 'failed', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "check_farm_memberships_invitation_email_status",
        "farm_memberships",
        type_="check",
    )
    op.drop_column("farm_memberships", "invitation_email_sent_at")
    op.drop_column("farm_memberships", "invitation_email_status")

"""Schedule account and farm deletion with a recovery window."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e37a91b2c4d6"
down_revision: Union[str, Sequence[str], None] = "d2e7f91a4b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_deletion_requested_at",
        "users",
        ["deletion_requested_at"],
    )
    op.add_column(
        "farms",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_farms_deletion_requested_at",
        "farms",
        ["deletion_requested_at"],
    )
    op.add_column(
        "farm_memberships",
        sa.Column("account_deletion_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "farm_memberships",
        sa.Column(
            "account_deletion_previous_status",
            sa.String(length=20),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("farm_memberships", "account_deletion_previous_status")
    op.drop_column("farm_memberships", "account_deletion_at")
    op.drop_index("ix_farms_deletion_requested_at", table_name="farms")
    op.drop_column("farms", "deletion_requested_at")
    op.drop_index("ix_users_deletion_requested_at", table_name="users")
    op.drop_column("users", "deletion_requested_at")

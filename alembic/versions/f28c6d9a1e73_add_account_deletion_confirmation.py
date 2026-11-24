"""Add one-time email confirmation for account deletion."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f28c6d9a1e73"
down_revision: Union[str, Sequence[str], None] = "e37a91b2c4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deletion_confirmation_token_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_users_deletion_confirmation_token_hash",
        "users",
        ["deletion_confirmation_token_hash"],
        unique=True,
    )
    op.add_column(
        "users",
        sa.Column(
            "deletion_confirmation_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "deletion_confirmation_expires_at")
    op.drop_index(
        "ix_users_deletion_confirmation_token_hash",
        table_name="users",
    )
    op.drop_column("users", "deletion_confirmation_token_hash")

"""Add app sessions and per-device login blocks."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4f68a19de20"
down_revision: Union[str, Sequence[str], None] = "d57f91af3052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_key", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=160), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_sessions_user_created_at",
        "user_sessions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_user_sessions_user_device_key",
        "user_sessions",
        ["user_id", "device_key"],
    )
    op.create_table(
        "blocked_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_key", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=160), nullable=False),
        sa.Column(
            "is_permanent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "device_key", name="uq_blocked_devices_user_device"
        ),
    )
    op.create_index("ix_blocked_devices_user_id", "blocked_devices", ["user_id"])
    op.add_column(
        "refresh_tokens",
        sa.Column("session_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_refresh_tokens_session_id_user_sessions",
        "refresh_tokens",
        "user_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_constraint(
        "fk_refresh_tokens_session_id_user_sessions",
        "refresh_tokens",
        type_="foreignkey",
    )
    op.drop_column("refresh_tokens", "session_id")
    op.drop_index("ix_blocked_devices_user_id", table_name="blocked_devices")
    op.drop_table("blocked_devices")
    op.drop_index("ix_user_sessions_user_device_key", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_created_at", table_name="user_sessions")
    op.drop_table("user_sessions")
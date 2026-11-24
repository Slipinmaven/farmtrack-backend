"""Track reminder creators and retryable farm-logo cleanup."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6d2e91f4a30"
down_revision: Union[str, Sequence[str], None] = "a6c3e9b71d42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_reminders_created_by_user_id_users",
        "reminders",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_reminders_created_by_user_id",
        "reminders",
        ["created_by_user_id"],
    )

    op.add_column(
        "notification_outbox",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_outbox_created_by_user_id_users",
        "notification_outbox",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_notification_outbox_created_by_user_id",
        "notification_outbox",
        ["created_by_user_id"],
    )

    op.create_table(
        "farm_logo_cleanup_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("logo_path", sa.String(length=512), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error_type", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_farm_logo_cleanup_jobs_available_at",
        "farm_logo_cleanup_jobs",
        ["available_at"],
    )

    op.execute(
        """
        UPDATE farms
        SET deletion_requested_at = users.deletion_requested_at
        FROM users
        WHERE farms.owner_id = users.id
          AND users.deletion_requested_at IS NOT NULL
          AND farms.deletion_requested_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE farm_memberships
        SET account_deletion_at = users.deletion_requested_at,
            account_deletion_previous_status = farm_memberships.status,
            status = 'revoked',
            revoked_at = users.deletion_requested_at
        FROM users
        WHERE farm_memberships.user_id = users.id
          AND users.deletion_requested_at IS NOT NULL
          AND farm_memberships.status IN ('active', 'invited')
          AND farm_memberships.account_deletion_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE user_sessions
        SET revoked_at = CURRENT_TIMESTAMP,
            revocation_reason = 'account_deletion'
        WHERE revoked_at IS NULL
          AND user_id IN (
              SELECT id FROM users WHERE deletion_requested_at IS NOT NULL
          )
        """
    )
    op.execute(
        """
        UPDATE refresh_tokens
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE revoked_at IS NULL
          AND user_id IN (
              SELECT id FROM users WHERE deletion_requested_at IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_farm_logo_cleanup_jobs_available_at",
        table_name="farm_logo_cleanup_jobs",
    )
    op.drop_table("farm_logo_cleanup_jobs")
    op.drop_index(
        "ix_notification_outbox_created_by_user_id",
        table_name="notification_outbox",
    )
    op.drop_constraint(
        "fk_notification_outbox_created_by_user_id_users",
        "notification_outbox",
        type_="foreignkey",
    )
    op.drop_column("notification_outbox", "created_by_user_id")
    op.drop_index("ix_reminders_created_by_user_id", table_name="reminders")
    op.drop_constraint(
        "fk_reminders_created_by_user_id_users",
        "reminders",
        type_="foreignkey",
    )
    op.drop_column("reminders", "created_by_user_id")

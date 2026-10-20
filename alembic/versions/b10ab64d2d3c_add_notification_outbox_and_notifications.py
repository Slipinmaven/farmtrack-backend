"""add notification outbox and notifications

Revision ID: b10ab64d2d3c
Revises: a12e5f90c763
Create Date: 2026-10-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b10ab64d2d3c"
down_revision: Union[str, Sequence[str], None] = "a12e5f90c763"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

notification_category = postgresql.ENUM(
    "alert",
    "transaction",
    "reminder",
    "farm",
    "security",
    name="notificationcategory",
    create_type=False,
)

notification_priority = postgresql.ENUM(
    "low",
    "normal",
    "high",
    "critical",
    name="notificationpriority",
    create_type=False,
)


def upgrade() -> None:
    notification_category.create(op.get_bind(), checkfirst=True)
    notification_priority.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(length=250), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_notification_outbox_dedupe_key"),
    )
    op.create_index("ix_notification_outbox_farm_id", "notification_outbox", ["farm_id"])
    op.create_index(
        "ix_notification_outbox_pending_available_at",
        "notification_outbox",
        ["available_at"],
        postgresql_where=sa.text("processed_at IS NULL AND failed_at IS NULL"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("category", notification_category, nullable=False),
        sa.Column("priority", notification_priority, nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["notification_outbox.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id", name="uq_notifications_source_event_id"),
    )
    op.create_index(
        "ix_notifications_recipient_farm_created",
        "notifications",
        ["recipient_user_id", "farm_id", "created_at", "id"],
    )
    op.create_index(
        "ix_notifications_unread_recipient_farm_created",
        "notifications",
        ["recipient_user_id", "farm_id", "created_at"],
        postgresql_where=sa.text("read_at IS NULL AND archived_at IS NULL"),
    )
    op.create_index(
        "ix_notifications_active_recipient_farm_created",
        "notifications",
        ["recipient_user_id", "farm_id", "created_at"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_active_recipient_farm_created",
        table_name="notifications",
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_index(
        "ix_notifications_unread_recipient_farm_created",
        table_name="notifications",
        postgresql_where=sa.text("read_at IS NULL AND archived_at IS NULL"),
    )
    op.drop_index("ix_notifications_recipient_farm_created", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(
        "ix_notification_outbox_pending_available_at",
        table_name="notification_outbox",
        postgresql_where=sa.text("processed_at IS NULL AND failed_at IS NULL"),
    )
    op.drop_index("ix_notification_outbox_farm_id", table_name="notification_outbox")
    op.drop_table("notification_outbox")

    notification_category.drop(op.get_bind(), checkfirst=True)
    notification_priority.drop(op.get_bind(), checkfirst=True)

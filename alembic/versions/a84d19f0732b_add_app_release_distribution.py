"""Add Android app release distribution.

Revision ID: a84d19f0732b
Revises: f4a8c21d9b07
Create Date: 2026-11-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a84d19f0732b"
down_revision: Union[str, Sequence[str], None] = "f4a8c21d9b07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("version_code", sa.Integer(), nullable=False),
        sa.Column(
            "platform",
            sa.String(length=20),
            server_default="android",
            nullable=False,
        ),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "is_latest",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("platform = 'android'", name="check_app_releases_android"),
        sa.CheckConstraint("version_code > 0", name="check_app_releases_version_code"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "version_code",
            name="uq_app_releases_platform_version_code",
        ),
    )
    op.create_index(
        "uq_app_releases_latest_platform",
        "app_releases",
        ["platform"],
        unique=True,
        postgresql_where=sa.text("is_latest IS TRUE"),
    )

    op.create_table(
        "download_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column(
            "delivery_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'failed')",
            name="check_download_tokens_delivery_status",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["app_releases.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_download_tokens_expires_at",
        "download_tokens",
        ["expires_at"],
    )
    op.create_index(
        "ix_download_tokens_release_id",
        "download_tokens",
        ["release_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_download_tokens_release_id", table_name="download_tokens")
    op.drop_index("ix_download_tokens_expires_at", table_name="download_tokens")
    op.drop_table("download_tokens")
    op.drop_index(
        "uq_app_releases_latest_platform",
        table_name="app_releases",
    )
    op.drop_table("app_releases")

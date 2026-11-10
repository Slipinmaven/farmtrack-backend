"""Use GitHub release assets for Android app distribution.

Revision ID: c6d9a1f4b827
Revises: a84d19f0732b
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d9a1f4b827"
down_revision: Union[str, Sequence[str], None] = "a84d19f0732b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "app_releases",
        "storage_path",
        new_column_name="legacy_storage_path",
        existing_type=sa.String(length=500),
        existing_nullable=False,
        nullable=True,
    )
    op.add_column(
        "app_releases",
        sa.Column("github_asset_id", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "check_app_releases_github_asset_id",
        "app_releases",
        "github_asset_id IS NULL OR github_asset_id > 0",
    )
    op.create_unique_constraint(
        "uq_app_releases_github_asset_id",
        "app_releases",
        ["github_asset_id"],
    )
    op.execute(
        "UPDATE app_releases SET is_active = false, is_latest = false "
        "WHERE github_asset_id IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE app_releases SET is_active = false, is_latest = false "
        "WHERE github_asset_id IS NOT NULL"
    )
    op.execute(
        "UPDATE app_releases SET legacy_storage_path = "
        "'github-asset:' || github_asset_id "
        "WHERE legacy_storage_path IS NULL"
    )
    op.drop_constraint(
        "uq_app_releases_github_asset_id",
        "app_releases",
        type_="unique",
    )
    op.drop_constraint(
        "check_app_releases_github_asset_id",
        "app_releases",
        type_="check",
    )
    op.drop_column("app_releases", "github_asset_id")
    op.alter_column(
        "app_releases",
        "legacy_storage_path",
        new_column_name="storage_path",
        existing_type=sa.String(length=500),
        existing_nullable=True,
        nullable=False,
    )

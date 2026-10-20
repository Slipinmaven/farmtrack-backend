"""Sync farm settings columns with the ORM model.

Revision ID: 8f3a0b74c921
Revises: fe19f168c84d
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "8f3a0b74c921"
down_revision: Union[str, Sequence[str], None] = "fe19f168c84d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


theme_mode_enum = postgresql.ENUM(
    "light",
    "dark",
    "system",
    name="thememode",
)


def upgrade() -> None:
    bind = op.get_bind()
    theme_mode_enum.create(bind, checkfirst=True)

    op.alter_column(
        "farm_settings",
        "log_path",
        new_column_name="logo_path",
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.execute(
        "UPDATE farm_settings SET theme_mode = 'system' WHERE theme_mode IS NULL"
    )
    op.execute(
        "UPDATE farm_settings SET theme_mode = lower(theme_mode) WHERE theme_mode IS NOT NULL"
    )
    op.alter_column(
        "farm_settings",
        "theme_mode",
        existing_type=sa.String(length=20),
        type_=theme_mode_enum,
        existing_nullable=True,
        nullable=False,
        server_default=sa.text("'system'"),
        postgresql_using="theme_mode::thememode",
    )


def downgrade() -> None:
    op.alter_column(
        "farm_settings",
        "theme_mode",
        existing_type=theme_mode_enum,
        type_=sa.String(length=20),
        existing_nullable=False,
        nullable=True,
        server_default=None,
        postgresql_using="theme_mode::text",
    )
    theme_mode_enum.drop(op.get_bind(), checkfirst=True)
    op.alter_column(
        "farm_settings",
        "logo_path",
        new_column_name="log_path",
        existing_type=sa.Text(),
        existing_nullable=True,
    )
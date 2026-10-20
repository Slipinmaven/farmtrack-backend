"""Align farm profile fields with the profile schema.

Revision ID: d57f91af3052
Revises: b10ab64d2d3c
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d57f91af3052"
down_revision: Union[str, Sequence[str], None] = "b10ab64d2d3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    oversized_records = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM farms "
            "WHERE char_length(name) > 150 OR char_length(email) > 255"
        )
    ).scalar_one()
    if oversized_records:
        raise RuntimeError(
            "Farm profile migration stopped: shorten farm names to 150 characters "
            "and farm emails to 255 characters before retrying."
        )

    op.execute(
        sa.text(
            "UPDATE farms SET maximum_chicken_capacity = NULL "
            "WHERE maximum_chicken_capacity = 0"
        )
    )
    op.drop_constraint(
        "check_maximum_chicken_capacity_non_negative",
        "farms",
        type_="check",
    )
    op.alter_column(
        "farms",
        "name",
        existing_type=sa.String(length=255),
        type_=sa.String(length=150),
        existing_nullable=False,
    )
    op.alter_column(
        "farms",
        "description",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "farms",
        "email",
        existing_type=sa.String(length=320),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.create_check_constraint(
        "check_maximum_chicken_capacity_positive",
        "farms",
        "maximum_chicken_capacity > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "check_maximum_chicken_capacity_positive",
        "farms",
        type_="check",
    )
    op.alter_column(
        "farms",
        "name",
        existing_type=sa.String(length=150),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        "farms",
        "description",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=True,
    )
    op.alter_column(
        "farms",
        "email",
        existing_type=sa.String(length=255),
        type_=sa.String(length=320),
        existing_nullable=True,
    )
    op.create_check_constraint(
        "check_maximum_chicken_capacity_non_negative",
        "farms",
        "maximum_chicken_capacity >= 0",
    )

"""Require farm names to be unique per owner.

Revision ID: c2a47e9b1d60
Revises: 8f3a0b74c921
Create Date: 2026-10-07
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c2a47e9b1d60"
down_revision: Union[str, Sequence[str], None] = "8f3a0b74c921"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_farms_owner_id_name",
        "farms",
        ["owner_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_farms_owner_id_name", "farms", type_="unique")
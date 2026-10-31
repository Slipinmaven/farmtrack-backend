"""Add farm memberships for shared farm access.

Revision ID: a6c91e02d4f7
Revises: f3b4c5d6e7f8
Create Date: 2026-10-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a6c91e02d4f7"
down_revision: Union[str, Sequence[str], None] = "f3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "farm_memberships",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("farm_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="invited",
            nullable=False,
        ),
        sa.Column("invited_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('owner', 'manager', 'worker')",
            name="check_farm_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'revoked')",
            name="check_farm_memberships_status",
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_farm_memberships_farm_id_farms",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_farm_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_id"],
            ["users.id"],
            name="fk_farm_memberships_invited_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_farm_memberships"),
        sa.UniqueConstraint(
            "farm_id",
            "user_id",
            name="uq_farm_memberships_farm_user",
        ),
    )
    op.create_index(
        "ix_farm_memberships_user_status",
        "farm_memberships",
        ["user_id", "status"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO farm_memberships (
            id, farm_id, user_id, role, status, invited_at, accepted_at
        )
        SELECT gen_random_uuid(), id, owner_id, 'owner', 'active', now(), now()
        FROM farms
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_farm_memberships_user_status",
        table_name="farm_memberships",
    )
    op.drop_table("farm_memberships")

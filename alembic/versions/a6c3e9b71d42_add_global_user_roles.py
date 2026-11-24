"""Add global user roles and promote the FarmTrack super admin."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6c3e9b71d42"
down_revision: Union[str, Sequence[str], None] = "f28c6d9a1e73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="USER",
        ),
    )
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('USER', 'SUPER_ADMIN')",
    )
    op.execute(
        sa.text(
            "UPDATE users SET role = 'SUPER_ADMIN' "
            "WHERE lower(trim(email)) = :email"
        ).bindparams(email="jasngigi1@gmail.com")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET role = 'USER' "
            "WHERE lower(trim(email)) = :email AND role = 'SUPER_ADMIN'"
        ).bindparams(email="jasngigi1@gmail.com")
    )
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")

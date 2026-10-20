"""add product sellable flag

Revision ID: f16a4d82c730
Revises: a3f6d92c1b47
Create Date: 2026-10-17 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f16a4d82c730"
down_revision: Union[str, Sequence[str], None] = "a3f6d92c1b47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "is_sellable",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.alter_column(
        "products",
        "is_sellable",
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    op.drop_column("products", "is_sellable")

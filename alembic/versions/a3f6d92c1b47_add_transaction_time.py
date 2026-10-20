"""Add optional local transaction time."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f6d92c1b47"
down_revision: Union[str, Sequence[str], None] = "f8c2a1d94e6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("transaction_time", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "transaction_time")

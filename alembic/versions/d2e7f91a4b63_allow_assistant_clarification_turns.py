"""Allow assistant messages that don't use a report period."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e7f91a4b63"
down_revision: Union[str, Sequence[str], None] = "c51e7b2a9d40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("assistant_messages") as batch_op:
        batch_op.alter_column(
            "from_date",
            existing_type=sa.Date(),
            nullable=True,
        )
        batch_op.alter_column(
            "to_date",
            existing_type=sa.Date(),
            nullable=True,
        )


def downgrade() -> None:
    op.execute(
        "UPDATE assistant_messages "
        "SET from_date = COALESCE(from_date, to_date, CURRENT_DATE), "
        "to_date = COALESCE(to_date, from_date, CURRENT_DATE) "
        "WHERE from_date IS NULL OR to_date IS NULL"
    )
    with op.batch_alter_table("assistant_messages") as batch_op:
        batch_op.alter_column(
            "from_date",
            existing_type=sa.Date(),
            nullable=False,
        )
        batch_op.alter_column(
            "to_date",
            existing_type=sa.Date(),
            nullable=False,
        )

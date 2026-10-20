"""Link farm activities to the app session that performed them."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "da1c9e32b74f"
down_revision: Union[str, Sequence[str], None] = "c4f68a19de20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "activities",
        sa.Column("session_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_activities_session_id_user_sessions",
        "activities",
        "user_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_activities_session_id", "activities", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_activities_session_id", table_name="activities")
    op.drop_constraint(
        "fk_activities_session_id_user_sessions",
        "activities",
        type_="foreignkey",
    )
    op.drop_column("activities", "session_id")
"""Track reminders already placed in the notification outbox."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a82e6c901f"
down_revision: Union[str, Sequence[str], None] = "c45a912e31bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column("notification_enqueued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_index("ix_reminders_pending_due_at", table_name="reminders")
    op.create_index(
        "ix_reminders_pending_due_at",
        "reminders",
        ["due_at"],
        postgresql_where=sa.text(
            "status = 'PENDING' AND notification_enqueued_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_reminders_pending_due_at", table_name="reminders")
    op.create_index(
        "ix_reminders_pending_due_at",
        "reminders",
        ["due_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_column("reminders", "notification_enqueued_at")
"""Add persistent AI assistant conversations."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c51e7b2a9d40"
down_revision: Union[str, Sequence[str], None] = "a7c91d4e2f63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("farm_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_conversations_user_farm_updated",
        "assistant_conversations",
        ["user_id", "farm_id", "updated_at", "id"],
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_assistant_messages_role",
        ),
        sa.CheckConstraint(
            "from_date <= to_date",
            name="ck_assistant_messages_date_range",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["assistant_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_messages_conversation_created",
        "assistant_messages",
        ["conversation_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_messages_conversation_created",
        table_name="assistant_messages",
    )
    op.drop_table("assistant_messages")
    op.drop_index(
        "ix_assistant_conversations_user_farm_updated",
        table_name="assistant_conversations",
    )
    op.drop_table("assistant_conversations")

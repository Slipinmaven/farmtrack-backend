"""add breeder chicken type

Revision ID: abae407fc96c
Revises: b8614426a25f
Create Date: 2026-10-08 11:05:19.633242

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'abae407fc96c'
down_revision: Union[str, Sequence[str], None] = 'b8614426a25f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TYPE chickentype ADD VALUE IF NOT EXISTS 'BREEDER' AFTER 'KIENYEJI'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE chicken_batches SET chicken_type = 'KIENYEJI' "
        "WHERE chicken_type = 'BREEDER'"
    )
    op.execute("ALTER TYPE chickentype RENAME TO chickentype_with_breeder")
    op.execute(
        "CREATE TYPE chickentype AS ENUM "
        "('LAYERS', 'BROILER', 'KIENYEJI', 'OTHER')"
    )
    op.execute(
        "ALTER TABLE chicken_batches ALTER COLUMN chicken_type "
        "TYPE chickentype USING chicken_type::text::chickentype"
    )
    op.execute("DROP TYPE chickentype_with_breeder")

"""add purchase workflow activity enums

Revision ID: 6af7195764c6
Revises: 93bba8c8a00d
Create Date: 2026-10-09 16:38:53.791967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6af7195764c6'
down_revision: Union[str, Sequence[str], None] = '93bba8c8a00d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'TRANSACTION_CREATED'")
    op.execute(
        "ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'TRANSACTION_PAYMENT_RECORDED'"
    )
    op.execute(
        "ALTER TYPE activitytype ADD VALUE IF NOT EXISTS 'PURCHASE_RECEIPT_CREATED'"
    )
    op.execute("ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'TRANSACTION'")
    op.execute(
        "ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'TRANSACTION_PAYMENT'"
    )
    op.execute(
        "ALTER TYPE activityentitytype ADD VALUE IF NOT EXISTS 'PURCHASE_RECEIPT'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass

"""persist inventory movement unit costs

Revision ID: d1f6c8a92b40
Revises: c7e4a19b52d0
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f6c8a92b40"
down_revision: Union[str, Sequence[str], None] = "c7e4a19b52d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_movements",
        sa.Column("unit_cost", sa.Numeric(14, 6), nullable=True),
    )
    op.create_check_constraint(
        "ck_inventory_movements_unit_cost_non_negative",
        "inventory_movements",
        "unit_cost IS NULL OR unit_cost >= 0",
    )
    op.execute(
        """
        UPDATE inventory_movements AS movement
        SET unit_cost = item.total_amount
            / NULLIF(item.quantity * item.conversion_factor, 0)
        FROM transaction_items AS item
        WHERE movement.movement_type = 'receipt'
          AND movement.source_type = 'transaction'
          AND movement.source_id = item.transaction_id
          AND movement.source_item_id = item.id
          AND movement.quantity_delta > 0
        """
    )
    op.execute(
        """
        UPDATE inventory_movements AS movement
        SET unit_cost = item.total_amount
            / NULLIF(item.quantity * item.conversion_factor, 0)
        FROM purchase_receipt_items AS receipt_item
        JOIN transaction_items AS item
          ON item.id = receipt_item.transaction_item_id
        WHERE movement.movement_type = 'receipt'
          AND movement.source_type = 'purchase_receipt'
          AND movement.source_id = receipt_item.purchase_receipt_id
          AND movement.source_item_id = receipt_item.id
          AND movement.quantity_delta > 0
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_inventory_movements_unit_cost_non_negative",
        "inventory_movements",
        type_="check",
    )
    op.drop_column("inventory_movements", "unit_cost")

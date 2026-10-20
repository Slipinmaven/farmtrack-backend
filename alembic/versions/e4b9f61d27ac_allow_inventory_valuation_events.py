"""allow quantity-neutral inventory valuation events

Revision ID: e4b9f61d27ac
Revises: d1f6c8a92b40
Create Date: 2026-10-19

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e4b9f61d27ac"
down_revision: Union[str, Sequence[str], None] = "d1f6c8a92b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_inventory_movements_farm_occurred",
        "inventory_movements",
        ["farm_id", "occurred_on"],
    )
    op.drop_constraint(
        "ck_inventory_movements_quantity_non_zero",
        "inventory_movements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_inventory_movements_quantity_non_zero",
        "inventory_movements",
        "quantity_delta <> 0 OR movement_type = 'valuation'",
    )
    op.drop_constraint(
        "ck_inventory_movements_type_valid",
        "inventory_movements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_inventory_movements_type_valid",
        "inventory_movements",
        "movement_type IN "
        "('opening_balance', 'receipt', 'sale', 'consumption', 'loss', "
        "'customer_return', 'supplier_return', 'settlement_received', "
        "'settlement_issued', 'adjustment', 'valuation')",
    )
    op.create_check_constraint(
        "ck_inventory_movements_valuation_has_cost",
        "inventory_movements",
        "movement_type <> 'valuation' OR unit_cost IS NOT NULL",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM inventory_movements
                WHERE movement_type = 'valuation'
            ) THEN
                RAISE EXCEPTION
                    'Cannot remove stock valuation support while valuation records exist.';
            END IF;
        END
        $$;
        """
    )
    op.drop_index(
        "ix_inventory_movements_farm_occurred",
        table_name="inventory_movements",
    )
    op.drop_constraint(
        "ck_inventory_movements_valuation_has_cost",
        "inventory_movements",
        type_="check",
    )
    op.drop_constraint(
        "ck_inventory_movements_type_valid",
        "inventory_movements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_inventory_movements_type_valid",
        "inventory_movements",
        "movement_type IN "
        "('opening_balance', 'receipt', 'sale', 'consumption', 'loss', "
        "'customer_return', 'supplier_return', 'settlement_received', "
        "'settlement_issued', 'adjustment')",
    )
    op.drop_constraint(
        "ck_inventory_movements_quantity_non_zero",
        "inventory_movements",
        type_="check",
    )
    op.create_check_constraint(
        "ck_inventory_movements_quantity_non_zero",
        "inventory_movements",
        "quantity_delta <> 0",
    )

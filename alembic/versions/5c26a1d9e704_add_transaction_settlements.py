"""add valued account settlements and opening stock snapshots

Revision ID: 5c26a1d9e704
Revises: 4e83b2a7c901
Create Date: 2026-10-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5c26a1d9e704"
down_revision: Union[str, Sequence[str], None] = "4e83b2a7c901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=24), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("total_value", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "lines",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_value > 0",
            name="ck_transaction_settlements_value_positive",
        ),
        sa.CheckConstraint(
            "direction IN ('contact_to_farm', 'farm_to_contact')",
            name="ck_transaction_settlements_direction_valid",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transaction_settlements_transaction_date",
        "transaction_settlements",
        ["transaction_id", "settlement_date"],
    )

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM chicken_losses cl
                    LEFT JOIN (
                        SELECT cti.batch_id,
                               COUNT(DISTINCT ti.product_id) AS product_count
                        FROM chicken_transaction_items cti
                        JOIN transaction_items ti ON ti.id = cti.transaction_item_id
                        JOIN products p ON p.id = ti.product_id
                        WHERE p.product_type = 'CHICKENS'
                        GROUP BY cti.batch_id
                    ) batch_products ON batch_products.batch_id = cl.batch_id
                    WHERE COALESCE(batch_products.product_count, 0) <> 1
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate chicken losses: a loss batch does not map to exactly one chicken product.';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM batch_blocks bb
                    LEFT JOIN (
                        SELECT cti.batch_id,
                               COUNT(DISTINCT ti.product_id) AS product_count
                        FROM chicken_transaction_items cti
                        JOIN transaction_items ti ON ti.id = cti.transaction_item_id
                        JOIN products p ON p.id = ti.product_id
                        WHERE p.product_type = 'CHICKENS'
                        GROUP BY cti.batch_id
                    ) batch_products ON batch_products.batch_id = bb.batch_id
                    WHERE bb.quantity > 0
                      AND COALESCE(batch_products.product_count, 0) <> 1
                ) THEN
                    RAISE EXCEPTION
                        'Cannot migrate current chicken stock: a stocked batch does not map to exactly one chicken product.';
                END IF;
            END
            $$;
            """
        )
    )

    op.execute(
        sa.text(
            """
            WITH chicken_batch_products AS (
                SELECT cti.batch_id,
                       (array_agg(ti.product_id ORDER BY ti.product_id))[1]
                           AS product_id,
                       COUNT(DISTINCT ti.product_id) AS product_count
                FROM chicken_transaction_items cti
                JOIN transaction_items ti ON ti.id = cti.transaction_item_id
                JOIN products p ON p.id = ti.product_id
                WHERE p.product_type = 'CHICKENS'
                GROUP BY cti.batch_id
            ),
            stock_deltas AS (
                SELECT ti.product_id,
                       ti.quantity * ti.conversion_factor AS quantity_delta
                FROM transaction_items ti
                JOIN transactions t ON t.id = ti.transaction_id
                JOIN products p ON p.id = ti.product_id
                WHERE t.transaction_type = 'PURCHASE'
                  AND t.status = 'COMPLETED'
                  AND p.product_type <> 'CHICKENS'
                UNION ALL
                SELECT ti.product_id,
                       -(ti.quantity * ti.conversion_factor)
                FROM transaction_items ti
                JOIN transactions t ON t.id = ti.transaction_id
                JOIN products p ON p.id = ti.product_id
                WHERE t.transaction_type = 'SALE'
                  AND t.status = 'COMPLETED'
                  AND p.product_type <> 'CHICKENS'
                UNION ALL
                SELECT ec.product_id, ec.quantity * ec.conversion_factor
                FROM egg_collections ec
                UNION ALL
                SELECT el.product_id, -(el.quantity * el.conversion_factor)
                FROM egg_losses el
                UNION ALL
                SELECT pc.product_id, -(pc.quantity * pc.conversion_factor)
                FROM product_consumptions pc
                UNION ALL
                SELECT ti.product_id, pri.quantity
                FROM purchase_receipt_items pri
                JOIN transaction_items ti ON ti.id = pri.transaction_item_id
                JOIN products p ON p.id = ti.product_id
                WHERE p.product_type = 'CHICKENS'
                UNION ALL
                SELECT ti.product_id, -sdi.quantity
                FROM sale_delivery_items sdi
                JOIN transaction_items ti ON ti.id = sdi.transaction_item_id
                JOIN products p ON p.id = ti.product_id
                WHERE p.product_type = 'CHICKENS'
                UNION ALL
                SELECT ti.product_id, sri.quantity
                FROM sale_return_items sri
                JOIN sale_returns sr ON sr.id = sri.sale_return_id
                JOIN transaction_items ti ON ti.id = sri.transaction_item_id
                JOIN products p ON p.id = ti.product_id
                WHERE sr.return_type = 'delivered_return'
                  AND p.product_type = 'CHICKENS'
                UNION ALL
                SELECT ti.product_id, -pri.quantity
                FROM purchase_return_items pri
                JOIN transaction_items ti ON ti.id = pri.transaction_item_id
                JOIN products p ON p.id = ti.product_id
                WHERE p.product_type = 'CHICKENS'
                UNION ALL
                SELECT ti.product_id, prip.quantity_received
                FROM purchase_replacement_items prip
                JOIN purchase_return_items pri
                  ON pri.id = prip.purchase_return_item_id
                JOIN transaction_items ti ON ti.id = pri.transaction_item_id
                JOIN products p ON p.id = ti.product_id
                WHERE p.product_type = 'CHICKENS'
                UNION ALL
                SELECT cbp.product_id, -cl.quantity
                FROM chicken_losses cl
                JOIN chicken_batch_products cbp ON cbp.batch_id = cl.batch_id
                WHERE cbp.product_count = 1
            ),
            balances AS (
                SELECT product_id, SUM(quantity_delta) AS quantity
                FROM stock_deltas
                GROUP BY product_id
            )
            INSERT INTO inventory_movements (
                id, farm_id, user_id, product_id, unit_id, quantity_delta,
                movement_type, occurred_on, notes
            )
            SELECT gen_random_uuid(),
                   p.farm_id,
                   f.owner_id,
                   p.id,
                   pu.unit_id,
                   b.quantity,
                   'opening_balance',
                   CURRENT_DATE,
                   'Opening balance migrated from existing stock records'
            FROM balances b
            JOIN products p ON p.id = b.product_id
            JOIN farms f ON f.id = p.farm_id
            JOIN product_units pu
              ON pu.product_id = p.id AND pu.is_base_unit IS TRUE
            WHERE b.quantity <> 0
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_settlements_transaction_date",
        table_name="transaction_settlements",
    )
    op.drop_table("transaction_settlements")

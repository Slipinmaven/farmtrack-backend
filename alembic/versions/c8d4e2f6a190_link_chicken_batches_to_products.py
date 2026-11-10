"""Link chicken batches to their inventory products.

Revision ID: c8d4e2f6a190
Revises: b7d2c8a4e901
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d4e2f6a190"
down_revision: Union[str, Sequence[str], None] = "b7d2c8a4e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chicken_batches",
        sa.Column("product_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chicken_batches_product_id_products",
        "chicken_batches",
        "products",
        ["product_id"],
        ["id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE chicken_batches AS batch
            SET product_id = movement.product_id
            FROM inventory_movements AS movement
            WHERE batch.product_id IS NULL
              AND batch.is_opening_stock IS TRUE
              AND movement.source_type = 'chicken_opening_batch'
              AND movement.source_id = batch.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH purchase_batch_links AS (
                SELECT
                    chicken_item.batch_id,
                    transaction_item.product_id
                FROM chicken_transaction_items AS chicken_item
                JOIN transaction_items AS transaction_item
                  ON transaction_item.id = chicken_item.transaction_item_id
                GROUP BY chicken_item.batch_id, transaction_item.product_id
            ),
            unambiguous_purchase_batch_links AS (
                SELECT
                    batch_id,
                    min(product_id::text)::uuid AS product_id
                FROM purchase_batch_links
                GROUP BY batch_id
                HAVING count(DISTINCT product_id) = 1
            )
            UPDATE chicken_batches AS batch
            SET product_id = link.product_id
            FROM unambiguous_purchase_batch_links AS link
            WHERE batch.product_id IS NULL
              AND batch.id = link.batch_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH batch_product_links AS (
                SELECT
                    (allocation->>'batch_id')::uuid AS batch_id,
                    (line->>'product_id')::uuid AS product_id
                FROM transaction_settlements AS settlement
                CROSS JOIN LATERAL
                    jsonb_array_elements(settlement.lines::jsonb) AS line
                CROSS JOIN LATERAL
                    jsonb_array_elements(
                        line->'chicken_placement'->'allocations'
                    ) AS allocation
                WHERE line->'chicken_placement'->'new_batch' IS NOT NULL
                  AND line->>'product_id' IS NOT NULL
                GROUP BY
                    (allocation->>'batch_id')::uuid,
                    (line->>'product_id')::uuid
            ),
            unambiguous_batch_links AS (
                SELECT
                    batch_id,
                    min(product_id::text)::uuid AS product_id
                FROM batch_product_links
                GROUP BY batch_id
                HAVING count(DISTINCT product_id) = 1
            )
            UPDATE chicken_batches AS batch
            SET product_id = link.product_id
            FROM unambiguous_batch_links AS link
            WHERE batch.product_id IS NULL
              AND batch.id = link.batch_id
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_chicken_batches_product_id_products",
        "chicken_batches",
        type_="foreignkey",
    )
    op.drop_column("chicken_batches", "product_id")

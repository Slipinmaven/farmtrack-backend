"""reset units to a measurement-only catalog

Revision ID: 4a0e6d9e1f2c
Revises: e7c55c14edc6
Create Date: 2026-10-08 14:40:00.000000

"""
from typing import Sequence, Union
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '4a0e6d9e1f2c'
down_revision: Union[str, Sequence[str], None] = 'e7c55c14edc6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UNIT_CATALOG = (
    ("Piece", "pc"),
    ("Pack", "pack"),
    ("Tray", "tray"),
    ("Box", "box"),
    ("Case", "case"),
    ("Crate", "crate"),
    ("Bag", "bag"),
    ("Bottle", "bottle"),
    ("Carton", "ctn"),
    ("Bundle", "bundle"),
    ("Sack", "sack"),
    ("Pallet", "pallet"),
    ("Dozen", "doz"),
    ("Gram", "g"),
    ("Kilogram", "kg"),
    ("Millilitre", "mL"),
    ("Litre", "L"),
)


def _unit_id(abbreviation: str):
    return uuid5(NAMESPACE_URL, f"farmtrack-unit:{abbreviation}")


def upgrade() -> None:
    """Upgrade schema."""
    product_units = sa.table(
        "product_units",
        sa.column("unit_id", sa.Uuid()),
    )
    units = sa.table(
        "units",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String(length=50)),
        sa.column("abbreviation", sa.String(length=10)),
    )

    op.execute(sa.delete(product_units))
    op.execute(sa.delete(units))

    op.get_bind().execute(
        postgresql.insert(units)
        .values(
            [
                {
                    "id": _unit_id(abbreviation),
                    "name": name,
                    "abbreviation": abbreviation,
                }
                for name, abbreviation in UNIT_CATALOG
            ]
        )
        .on_conflict_do_nothing()
    )


def downgrade() -> None:
    """Downgrade schema."""
    product_units = sa.table(
        "product_units",
        sa.column("unit_id", sa.Uuid()),
    )
    units = sa.table(
        "units",
        sa.column("id", sa.Uuid()),
    )

    op.execute(sa.delete(product_units))
    op.execute(sa.delete(units))

    op.get_bind().execute(
        postgresql.insert(units)
        .values(
            [
                {
                    "id": _unit_id(abbreviation),
                    "name": name,
                    "abbreviation": abbreviation,
                }
                for name, abbreviation in UNIT_CATALOG
            ]
        )
        .on_conflict_do_nothing()
    )

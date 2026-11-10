"""Enforce farm-scoped contact phone and email uniqueness."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a8c21d9b07"
down_revision: Union[str, Sequence[str], None] = "e9a1c4d7b602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("phone_normalized", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("email_normalized", sa.String(length=255), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE contacts
            SET phone_normalized = NULLIF(regexp_replace(phone, '[^0-9]', '', 'g'), ''),
                email_normalized = NULLIF(lower(btrim(email)), '')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE contacts
            SET phone_normalized = NULL
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY farm_id, phone_normalized
                               ORDER BY created_at, id
                           ) AS duplicate_number
                    FROM contacts
                    WHERE phone_normalized IS NOT NULL
                ) ranked
                WHERE duplicate_number > 1
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE contacts
            SET email_normalized = NULL
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY farm_id, email_normalized
                               ORDER BY created_at, id
                           ) AS duplicate_number
                    FROM contacts
                    WHERE email_normalized IS NOT NULL
                ) ranked
                WHERE duplicate_number > 1
            )
            """
        )
    )
    op.create_unique_constraint(
        "uq_contacts_farm_phone_normalized",
        "contacts",
        ["farm_id", "phone_normalized"],
    )
    op.create_unique_constraint(
        "uq_contacts_farm_email_normalized",
        "contacts",
        ["farm_id", "email_normalized"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_contacts_farm_email_normalized",
        "contacts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_contacts_farm_phone_normalized",
        "contacts",
        type_="unique",
    )
    op.drop_column("contacts", "email_normalized")
    op.drop_column("contacts", "phone_normalized")

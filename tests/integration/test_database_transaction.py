from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.contact import Contact


@pytest.mark.asyncio
async def test_service_commit_is_visible_then_outer_transaction_rolls_back(
    api_client: AsyncClient,
    two_farm_contacts,
    db_session_factory: async_sessionmaker[AsyncSession],
    rollback_probe,
):
    response = await api_client.post(
        f"/api/v1/farms/{two_farm_contacts.farm_a_id}/contacts",
        json={"name": "Rollback probe contact", "role": "customer"},
    )

    assert response.status_code == 201
    contact_id = UUID(response.json()["id"])
    rollback_probe.contact_ids.append(contact_id)

    async with db_session_factory() as session:
        persisted_contact = await session.scalar(
            select(Contact).where(Contact.id == contact_id)
        )
        assert persisted_contact is not None
        assert persisted_contact.name == "Rollback probe contact"
        assert persisted_contact.farm_id == two_farm_contacts.farm_a_id


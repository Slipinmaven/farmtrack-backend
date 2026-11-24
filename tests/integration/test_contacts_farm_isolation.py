import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_farm_owner_can_read_own_contact(
    api_client: AsyncClient,
    test_app,
    two_farm_contacts,
    db_connection,
):
    response = await api_client.get(
        f"/api/v1/farms/{two_farm_contacts.farm_a_id}"
        f"/contacts/{two_farm_contacts.contact_a_id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(two_farm_contacts.contact_a_id)
    assert body["farm_id"] == str(two_farm_contacts.farm_a_id)
    assert body["name"] == two_farm_contacts.contact_a_name
    assert body["roles"] == ["customer"]

    session_connections = test_app.state.test_database_session_connections
    assert session_connections
    assert all(
        connection.sync_connection is db_connection.sync_connection
        for connection in session_connections
    )


@pytest.mark.asyncio
async def test_farm_owner_cannot_read_foreign_contact_by_id(
    api_client: AsyncClient,
    test_app,
    two_farm_contacts,
    db_connection,
):
    response = await api_client.get(
        f"/api/v1/farms/{two_farm_contacts.farm_a_id}"
        f"/contacts/{two_farm_contacts.contact_b_id}"
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert two_farm_contacts.contact_b_name not in response.text
    assert two_farm_contacts.contact_b_notes not in response.text
    assert str(two_farm_contacts.contact_b_id) not in response.text

    session_connections = test_app.state.test_database_session_connections
    assert session_connections
    assert all(
        connection.sync_connection is db_connection.sync_connection
        for connection in session_connections
    )

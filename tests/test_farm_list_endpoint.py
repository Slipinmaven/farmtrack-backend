from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.endpoints.farm import list_farm_members, list_farms


def make_farm(owner_id, email):
    return SimpleNamespace(
        id=uuid4(),
        owner_id=owner_id,
        name="North Field",
        description=None,
        location=None,
        phone_number=None,
        email=email,
        maximum_chicken_capacity=None,
        is_active=True,
        setup_completed_at=None,
        deletion_requested_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        farm_settings=None,
    )


@pytest.mark.asyncio
async def test_list_farms_hides_farm_email_from_non_owners():
    current_user = SimpleNamespace(id=uuid4())
    owner_farm = make_farm(current_user.id, "owner@example.com")
    member_farm = make_farm(uuid4(), "private-owner@example.com")

    class FarmServiceStub:
        async def get_user_farms(self, *_args, **_kwargs):
            return [owner_farm, member_farm]

    responses = await list_farms(current_user=current_user, service=FarmServiceStub())

    assert responses[0].email == "owner@example.com"
    assert responses[1].email is None


@pytest.mark.asyncio
async def test_list_farm_members_hides_owner_email_from_managers():
    owner_id = uuid4()
    manager_id = uuid4()
    farm_id = uuid4()
    now = datetime.now(UTC)
    owner_membership = SimpleNamespace(
        id=uuid4(),
        farm_id=farm_id,
        user_id=owner_id,
        user=SimpleNamespace(email="private-owner@example.com"),
        farm=SimpleNamespace(name="North Field"),
        role="owner",
        status="active",
        invited_by_id=None,
        invited_at=now,
        accepted_at=now,
        revoked_at=None,
        invitation_email_status="not_configured",
        invitation_email_sent_at=None,
    )

    class MembershipServiceStub:
        async def list_members(self, _farm):
            return [owner_membership]

    responses = await list_farm_members(
        farm=SimpleNamespace(id=farm_id, owner_id=owner_id),
        current_user=SimpleNamespace(id=manager_id),
        service=MembershipServiceStub(),
    )

    assert responses[0].role == "owner"
    assert responses[0].email is None

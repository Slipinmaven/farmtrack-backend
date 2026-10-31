from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, ResourceNotFoundError
from app.core.request_context import auth_user_id_context
from app.dependencies.farm import get_farm_manager, get_farm_owner, get_owned_farm
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    FarmMembershipStatus,
    FarmRole,
)
from app.services.activity_service import ActivityService
from app.services.farm_membership_service import FarmMembershipService


class FakeFarmRepository:
    def __init__(self, farm, memberships):
        self.farm = farm
        self.memberships = memberships

    async def get_by_id(self, farm_id):
        return self.farm if self.farm.id == farm_id else None

    async def get_membership(self, farm_id, user_id):
        return self.memberships.get((farm_id, user_id))


def make_user():
    return SimpleNamespace(id=uuid4(), email="user@example.com", is_active=True)


def make_farm(owner_id):
    return SimpleNamespace(id=uuid4(), owner_id=owner_id)


@pytest.mark.asyncio
async def test_active_farm_member_can_access_farm():
    owner = make_user()
    member = make_user()
    farm = make_farm(owner.id)
    membership = SimpleNamespace(status=FarmMembershipStatus.ACTIVE, role=FarmRole.WORKER)
    repository = FakeFarmRepository(farm, {(farm.id, member.id): membership})

    assert await get_owned_farm(farm.id, member, repository) is farm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "membership_status",
    [FarmMembershipStatus.INVITED, FarmMembershipStatus.REVOKED],
)
async def test_pending_or_revoked_member_cannot_access_farm(membership_status):
    owner = make_user()
    member = make_user()
    farm = make_farm(owner.id)
    membership = SimpleNamespace(status=membership_status, role=FarmRole.WORKER)
    repository = FakeFarmRepository(farm, {(farm.id, member.id): membership})

    with pytest.raises(AuthorizationError):
        await get_owned_farm(farm.id, member, repository)


@pytest.mark.asyncio
async def test_nonmember_cannot_access_another_users_farm():
    owner = make_user()
    nonmember = make_user()
    farm = make_farm(owner.id)
    repository = FakeFarmRepository(farm, {})

    with pytest.raises(AuthorizationError):
        await get_owned_farm(farm.id, nonmember, repository)


@pytest.mark.asyncio
async def test_farm_owner_can_access_farm_without_membership_lookup():
    owner = make_user()
    farm = make_farm(owner.id)
    repository = FakeFarmRepository(farm, {})

    assert await get_owned_farm(farm.id, owner, repository) is farm


@pytest.mark.asyncio
async def test_worker_cannot_manage_farm_settings_or_delete_farm():
    owner = make_user()
    worker = make_user()
    farm = make_farm(owner.id)
    membership = SimpleNamespace(status=FarmMembershipStatus.ACTIVE, role=FarmRole.WORKER)
    repository = FakeFarmRepository(farm, {(farm.id, worker.id): membership})

    with pytest.raises(AuthorizationError):
        await get_farm_manager(farm, worker, repository)
    with pytest.raises(AuthorizationError):
        await get_farm_owner(farm, worker)


@pytest.mark.asyncio
async def test_active_manager_can_manage_farm():
    owner = make_user()
    manager = make_user()
    farm = make_farm(owner.id)
    membership = SimpleNamespace(status=FarmMembershipStatus.ACTIVE, role=FarmRole.MANAGER)
    repository = FakeFarmRepository(farm, {(farm.id, manager.id): membership})

    assert await get_farm_manager(farm, manager, repository) is farm


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def commit(self):
        return None


class FakeMembershipRepository:
    def __init__(self):
        self.memberships = {}

    async def get_by_farm_and_user(self, farm_id, user_id):
        return self.memberships.get((farm_id, user_id))

    async def create(self, membership):
        membership.id = uuid4()
        self.memberships[(membership.farm_id, membership.user_id)] = membership
        return membership

    async def get_by_id_for_update(self, membership_id):
        return next(
            (item for item in self.memberships.values() if item.id == membership_id),
            None,
        )

    async def update(self, membership):
        return membership

class FakeUserRepository:
    def __init__(self, user):
        self.user = user

    async def get_by_email(self, email):
        return self.user if self.user.email == email else None


class FakeActivityRepository:
    async def create(self, activity):
        return activity


@pytest.mark.asyncio
async def test_activity_attributes_shared_farm_changes_to_authenticated_member():
    owner = make_user()
    worker = make_user()
    farm = make_farm(owner.id)
    service = ActivityService(
        repository=FakeActivityRepository(),
        unit_of_work=FakeUnitOfWork(),
    )
    context_token = auth_user_id_context.set(worker.id)
    try:
        activity = await service.record(
            farm_id=farm.id,
            user_id=owner.id,
            activity_type=ActivityType.FARM_UPDATED,
            entity_type=ActivityEntityType.FARM,
            entity_id=farm.id,
        )
    finally:
        auth_user_id_context.reset(context_token)

    assert activity.user_id == worker.id


@pytest.mark.asyncio
async def test_invite_creates_pending_membership_for_registered_account():
    owner = make_user()
    invited_user = make_user()
    farm = make_farm(owner.id)
    repository = FakeMembershipRepository()
    service = FarmMembershipService(
        membership_repository=repository,
        user_repository=FakeUserRepository(invited_user),
        unit_of_work=FakeUnitOfWork(),
    )

    membership = await service.invite(
        farm=farm,
        actor=owner,
        email=invited_user.email,
        role=FarmRole.WORKER,
    )

    assert membership.user_id == invited_user.id
    assert membership.status == FarmMembershipStatus.INVITED
    assert membership.invited_by_id == owner.id


@pytest.mark.asyncio
async def test_manager_cannot_invite_manager():
    owner = make_user()
    manager = make_user()
    invited_user = make_user()
    farm = make_farm(owner.id)
    service = FarmMembershipService(
        membership_repository=FakeMembershipRepository(),
        user_repository=FakeUserRepository(invited_user),
        unit_of_work=FakeUnitOfWork(),
    )

    with pytest.raises(AuthorizationError):
        await service.invite(
            farm=farm,
            actor=manager,
            email=invited_user.email,
            role=FarmRole.MANAGER,
        )


@pytest.mark.asyncio
async def test_invitation_can_only_be_accepted_by_invited_user():
    owner = make_user()
    invitee = make_user()
    other_user = make_user()
    farm = make_farm(owner.id)
    membership = SimpleNamespace(
        id=uuid4(),
        farm_id=farm.id,
        farm=farm,
        user_id=invitee.id,
        role=FarmRole.WORKER,
        status=FarmMembershipStatus.INVITED,
        invited_by_id=owner.id,
        invited_at=datetime.now(timezone.utc),
        accepted_at=None,
        revoked_at=None,
    )
    repository = FakeMembershipRepository()
    repository.memberships[(farm.id, invitee.id)] = membership
    service = FarmMembershipService(
        membership_repository=repository,
        user_repository=FakeUserRepository(invitee),
        unit_of_work=FakeUnitOfWork(),
    )

    with pytest.raises(ResourceNotFoundError):
        await service.accept_invitation(membership_id=membership.id, user=other_user)

    accepted = await service.accept_invitation(membership_id=membership.id, user=invitee)
    assert accepted.status == FarmMembershipStatus.ACTIVE
    assert accepted.accepted_at is not None

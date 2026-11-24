from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.exceptions import AuthenticationError, ConflictError
from app.services.data_deletion_service import (
    DELETION_GRACE_PERIOD,
    DataDeletionService,
)


@pytest.fixture(autouse=True)
def stub_password_verification(monkeypatch):
    monkeypatch.setattr(
        "app.services.data_deletion_service.verify_password",
        lambda password, password_hash: (
            password == "correct horse battery staple"
            and password_hash == "encoded"
        ),
    )


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values)

    def all(self):
        return self.values


class FakeSession:
    def __init__(self, *, memberships=(), farms=()):
        self.memberships = list(memberships)
        self.farms = list(farms)
        self.statements = []

    async def scalars(self, statement):
        sql = str(statement).lower()
        self.statements.append(sql)
        if "from farm_memberships" in sql:
            return FakeScalars(self.memberships)
        if "from farms" in sql:
            return FakeScalars(self.farms)
        return FakeScalars([])


class FakeUnitOfWork:
    def __init__(self, session):
        self.session = session
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def commit(self):
        self.commits += 1


class FakeUserRepository:
    def __init__(self, user, additional_users=()):
        self.user = user
        self.additional_users = list(additional_users)

    async def get_by_id(self, user_id):
        return next(
            (
                user
                for user in [self.user, *self.additional_users]
                if user.id == user_id
            ),
            None,
        )

    async def get_by_id_for_update(self, user_id):
        return await self.get_by_id(user_id)

    async def get_by_email(self, email):
        return self.user if self.user.email == email else None

    async def get_by_email_for_update(self, email):
        return await self.get_by_email(email)

    async def get_by_deletion_confirmation_hash_for_update(self, token_hash):
        if self.user.deletion_confirmation_token_hash == token_hash:
            return self.user
        return None


class FakeFarmRepository:
    def __init__(self, farms, memberships=()):
        self.farms = farms
        self.memberships = list(memberships)

    async def list_owned_for_update(self, owner_id):
        return [farm for farm in self.farms if farm.owner_id == owner_id]

    async def list_memberships_for_user_for_update(self, user_id):
        return [
            membership
            for membership in self.memberships
            if membership.user_id == user_id
        ]

    async def get_by_owner_and_id_for_update(self, farm_id, owner_id):
        return next(
            (
                farm
                for farm in self.farms
                if farm.id == farm_id and farm.owner_id == owner_id
            ),
            None,
        )

    async def get_by_id_for_update(self, farm_id):
        return next((farm for farm in self.farms if farm.id == farm_id), None)

    async def get_membership(self, farm_id, user_id):
        return next(
            (
                membership
                for membership in self.memberships
                if membership.farm_id == farm_id and membership.user_id == user_id
            ),
            None,
        )


class FakeSessionRepository:
    def __init__(self):
        self.revoked = []

    async def revoke_for_user(self, user_id, revoked_at, reason):
        self.revoked.append((user_id, revoked_at, reason))


class FakeRefreshTokenRepository:
    def __init__(self):
        self.revoked = []

    async def revoke_for_user(self, user_id, revoked_at):
        self.revoked.append((user_id, revoked_at))


class FakeEmailService:
    is_configured = True

    def __init__(self):
        self.messages = []

    async def send_account_deletion_notice(self, **message):
        self.messages.append(message)

    async def send_farm_deletion_notice(self, **message):
        self.messages.append(message)

    async def send_account_restored_notice(self, **message):
        self.messages.append(message)

    async def send_farm_left_confirmation(self, **message):
        self.messages.append({"kind": "member", **message})

    async def send_farm_member_left_notice(self, **message):
        self.messages.append({"kind": "owner", **message})


def make_user():
    return SimpleNamespace(
        id=uuid4(),
        email="owner@example.com",
        password_hash="encoded",
        deletion_requested_at=None,
        deletion_confirmation_token_hash=None,
        deletion_confirmation_expires_at=None,
    )


def make_farm(owner_id):
    return SimpleNamespace(
        id=uuid4(),
        owner_id=owner_id,
        name="Test farm",
        deletion_requested_at=None,
    )


def make_service(*, user, farms=(), memberships=(), additional_users=()):
    session = FakeSession(memberships=memberships, farms=farms)
    unit_of_work = FakeUnitOfWork(session)
    session_repository = FakeSessionRepository()
    token_repository = FakeRefreshTokenRepository()
    email_service = FakeEmailService()
    service = DataDeletionService(
        user_repository=FakeUserRepository(user, additional_users),
        farm_repository=FakeFarmRepository(farms, memberships),
        user_session_repository=session_repository,
        refresh_token_repository=token_repository,
        unit_of_work=unit_of_work,
        email_service=email_service,
    )
    return service, unit_of_work, session_repository, token_repository


@pytest.mark.asyncio
async def test_schedule_farm_deletion_requires_password_and_sets_grace_period():
    owner = make_user()
    farm = make_farm(owner.id)
    service, unit_of_work, _, _ = make_service(user=owner, farms=[farm])

    scheduled_for, notification_sent = await service.schedule_farm_deletion(
        farm_id=farm.id,
        owner_id=owner.id,
        current_password=SecretStr("correct horse battery staple"),
    )

    assert farm.deletion_requested_at is not None
    assert scheduled_for - farm.deletion_requested_at == DELETION_GRACE_PERIOD
    assert notification_sent is True
    assert service.email_service.messages == [{
        "recipient_email": owner.email,
        "farm_name": farm.name,
        "scheduled_for": scheduled_for,
    }]
    assert unit_of_work.commits == 1


@pytest.mark.asyncio
async def test_farm_deletion_rejects_an_incorrect_password():
    owner = make_user()
    farm = make_farm(owner.id)
    service, unit_of_work, _, _ = make_service(user=owner, farms=[farm])

    with pytest.raises(AuthenticationError):
        await service.schedule_farm_deletion(
            farm_id=farm.id,
            owner_id=owner.id,
            current_password=SecretStr("wrong password"),
        )

    assert farm.deletion_requested_at is None
    assert unit_of_work.commits == 0


@pytest.mark.asyncio
async def test_leaving_farm_emails_member_and_owner_after_commit():
    owner = make_user()
    owner.email = "owner@example.com"
    member = make_user()
    member.email = "member@example.com"
    farm = make_farm(owner.id)
    membership = SimpleNamespace(
        farm_id=farm.id,
        user_id=member.id,
        status="active",
        revoked_at=None,
    )
    service, unit_of_work, _, _ = make_service(
        user=member,
        farms=[farm],
        memberships=[membership],
        additional_users=[owner],
    )

    email_status = await service.leave_farm(
        farm_id=farm.id,
        user_id=member.id,
        current_password=SecretStr("correct horse battery staple"),
    )

    assert membership.status == "revoked"
    assert membership.revoked_at is not None
    assert unit_of_work.commits == 1
    assert email_status == {
        "member_email_sent": True,
        "owner_email_sent": True,
    }
    assert service.email_service.messages == [
        {
            "kind": "owner",
            "recipient_email": owner.email,
            "farm_name": farm.name,
            "member_email": member.email,
        },
        {
            "kind": "member",
            "recipient_email": member.email,
            "farm_name": farm.name,
            "owner_notified": True,
        },
    ]


@pytest.mark.asyncio
async def test_leave_email_failure_does_not_reverse_leave_or_skip_owner_notice():
    owner = make_user()
    member = make_user()
    member.email = "member@example.com"
    farm = make_farm(owner.id)
    membership = SimpleNamespace(
        farm_id=farm.id,
        user_id=member.id,
        status="active",
        revoked_at=None,
    )
    service, unit_of_work, _, _ = make_service(
        user=member,
        farms=[farm],
        memberships=[membership],
        additional_users=[owner],
    )

    async def fail_member_email(**_message):
        raise RuntimeError("private gateway error")

    service.email_service.send_farm_left_confirmation = fail_member_email
    email_status = await service.leave_farm(
        farm_id=farm.id,
        user_id=member.id,
        current_password=SecretStr("correct horse battery staple"),
    )

    assert membership.status == "revoked"
    assert unit_of_work.commits == 1
    assert email_status == {
        "member_email_sent": False,
        "owner_email_sent": True,
    }
    assert len(service.email_service.messages) == 1
    assert service.email_service.messages[0]["kind"] == "owner"


@pytest.mark.asyncio
async def test_farm_deletion_notice_failure_does_not_cancel_scheduled_deletion():
    owner = make_user()
    farm = make_farm(owner.id)
    farm.name = "North Field"
    service, unit_of_work, _, _ = make_service(user=owner, farms=[farm])

    async def fail_sending(**_message):
        raise RuntimeError("private gateway error")

    service.email_service.send_farm_deletion_notice = fail_sending
    scheduled_for, notification_sent = await service.schedule_farm_deletion(
        farm_id=farm.id,
        owner_id=owner.id,
        current_password=SecretStr("correct horse battery staple"),
    )

    assert notification_sent is False
    assert farm.deletion_requested_at is not None
    assert scheduled_for - farm.deletion_requested_at == DELETION_GRACE_PERIOD
    assert unit_of_work.commits == 1


@pytest.mark.asyncio
async def test_farm_deletion_cannot_be_scheduled_twice():
    owner = make_user()
    farm = make_farm(owner.id)
    farm.deletion_requested_at = datetime.now(UTC)
    service, unit_of_work, _, _ = make_service(user=owner, farms=[farm])

    with pytest.raises(ConflictError, match="already been scheduled"):
        await service.schedule_farm_deletion(
            farm_id=farm.id,
            owner_id=owner.id,
            current_password=SecretStr("correct horse battery staple"),
        )

    assert unit_of_work.commits == 0


def test_scheduled_account_is_denied_farm_access():
    from app.core.exceptions import AuthorizationError
    from app.dependencies.auth import require_account_not_pending_deletion

    owner = make_user()
    owner.deletion_requested_at = datetime.now(UTC)

    with pytest.raises(AuthorizationError, match="Farm access is paused"):
        require_account_not_pending_deletion(owner)


def test_account_without_deletion_request_retains_farm_access():
    from app.dependencies.auth import require_account_not_pending_deletion

    owner = make_user()

    assert require_account_not_pending_deletion(owner) is owner


@pytest.mark.asyncio
async def test_account_deletion_request_starts_countdown_and_sends_notice():
    owner = make_user()
    owned_farm = make_farm(owner.id)
    other_owner_farm = make_farm(uuid4())
    other_farm_membership = SimpleNamespace(
        user_id=owner.id,
        farm_id=other_owner_farm.id,
        status="invited",
        revoked_at=None,
        account_deletion_at=None,
        account_deletion_previous_status=None,
    )
    service, unit_of_work, sessions, tokens = make_service(
        user=owner,
        farms=[owned_farm, other_owner_farm],
        memberships=[other_farm_membership],
    )

    scheduled_for, notification_sent = await service.schedule_account_deletion(
        owner.id,
        SecretStr("correct horse battery staple"),
    )

    assert owner.deletion_requested_at is not None
    assert scheduled_for - owner.deletion_requested_at == DELETION_GRACE_PERIOD
    assert notification_sent is True
    assert owner.deletion_confirmation_token_hash is None
    assert owner.deletion_confirmation_expires_at is None
    assert owned_farm.deletion_requested_at == owner.deletion_requested_at
    assert other_owner_farm.deletion_requested_at is None
    assert other_farm_membership.status == "revoked"
    assert other_farm_membership.account_deletion_at == owner.deletion_requested_at
    assert other_farm_membership.account_deletion_previous_status == "invited"
    assert len(sessions.revoked) == 1
    assert sessions.revoked[0][0] == owner.id
    assert sessions.revoked[0][2] == "account_deletion"
    assert len(tokens.revoked) == 1
    assert tokens.revoked[0][0] == owner.id
    assert unit_of_work.commits == 1
    assert len(service.email_service.messages) == 1
    email = service.email_service.messages[0]
    assert email["recipient_email"] == owner.email
    assert email["scheduled_for"] == scheduled_for
    status = await service.get_account_deletion_status(owner.id)
    assert status["status"] == "scheduled"
    assert status["scheduled_for"] == scheduled_for


@pytest.mark.asyncio
async def test_failed_notification_does_not_cancel_deletion_request():
    owner = make_user()
    service, unit_of_work, _, _ = make_service(user=owner)

    async def fail_sending(**_message):
        raise RuntimeError("private gateway error")

    service.email_service.send_account_deletion_notice = fail_sending
    scheduled_for, notification_sent = await service.schedule_account_deletion(
        owner.id,
        SecretStr("correct horse battery staple"),
    )

    assert notification_sent is False
    assert owner.deletion_requested_at is not None
    assert scheduled_for - owner.deletion_requested_at == DELETION_GRACE_PERIOD
    assert unit_of_work.commits == 1


@pytest.mark.asyncio
async def test_unconfigured_notification_gateway_does_not_block_deletion():
    owner = make_user()
    service, unit_of_work, _, _ = make_service(user=owner)
    service.email_service.is_configured = False

    scheduled_for, notification_sent = await service.schedule_account_deletion(
        owner.id,
        SecretStr("correct horse battery staple"),
    )

    assert notification_sent is False
    assert owner.deletion_requested_at is not None
    assert scheduled_for - owner.deletion_requested_at == DELETION_GRACE_PERIOD
    assert service.email_service.messages == []
    assert unit_of_work.commits == 1


@pytest.mark.asyncio
async def test_confirmation_starts_30_day_period_and_token_is_single_use():
    owner = make_user()
    service, unit_of_work, sessions, tokens = make_service(user=owner)
    raw_token = "legacy-confirmation-token"
    owner.deletion_confirmation_token_hash = sha256(raw_token.encode()).hexdigest()
    owner.deletion_confirmation_expires_at = datetime.now(UTC) + timedelta(hours=1)

    scheduled_for = await service.confirm_account_deletion(raw_token)

    assert owner.deletion_requested_at is not None
    assert scheduled_for - owner.deletion_requested_at == DELETION_GRACE_PERIOD
    assert owner.deletion_confirmation_token_hash is None
    assert owner.deletion_confirmation_expires_at is None
    assert len(sessions.revoked) == 1
    assert sessions.revoked[0][0] == owner.id
    assert len(tokens.revoked) == 1
    assert tokens.revoked[0][0] == owner.id
    status = await service.get_account_deletion_status(owner.id)
    assert status["status"] == "scheduled"
    assert unit_of_work.commits == 1
    with pytest.raises(ConflictError):
        await service.confirm_account_deletion(raw_token)


@pytest.mark.asyncio
async def test_expired_confirmation_link_does_not_schedule_account_deletion():
    owner = make_user()
    service, _, _, _ = make_service(user=owner)
    raw_token = "legacy-confirmation-token"
    owner.deletion_confirmation_token_hash = sha256(raw_token.encode()).hexdigest()
    owner.deletion_confirmation_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(ConflictError):
        await service.confirm_account_deletion(raw_token)

    assert owner.deletion_requested_at is None


@pytest.mark.asyncio
async def test_account_deletion_can_be_canceled_with_password():
    owner = make_user()
    owner.deletion_requested_at = datetime.now(UTC)
    service, unit_of_work, _, _ = make_service(user=owner)

    await service.cancel_account_deletion(
        owner.id,
        SecretStr("correct horse battery staple"),
    )

    assert owner.deletion_requested_at is None
    assert unit_of_work.commits == 1
    assert service.email_service.messages == [
        {"recipient_email": owner.email},
    ]


@pytest.mark.asyncio
async def test_account_restore_restores_membership_status_and_matching_farms():
    owner = make_user()
    deletion_at = datetime.now(UTC)
    owner.deletion_requested_at = deletion_at
    farm = make_farm(owner.id)
    farm.deletion_requested_at = deletion_at
    membership = SimpleNamespace(
        user_id=owner.id,
        status="revoked",
        revoked_at=deletion_at,
        account_deletion_at=deletion_at,
        account_deletion_previous_status="invited",
    )
    service, unit_of_work, _, _ = make_service(
        user=owner,
        farms=[farm],
        memberships=[membership],
    )

    await service.restore_account(
        email=owner.email,
        password=SecretStr("correct horse battery staple"),
    )

    assert owner.deletion_requested_at is None
    assert farm.deletion_requested_at is None
    assert membership.status == "invited"
    assert membership.revoked_at is None
    assert membership.account_deletion_at is None
    assert membership.account_deletion_previous_status is None
    assert unit_of_work.commits == 1
    assert service.email_service.messages == [
        {"recipient_email": owner.email},
    ]


@pytest.mark.asyncio
async def test_account_restore_email_failure_does_not_reverse_restoration():
    owner = make_user()
    owner.deletion_requested_at = datetime.now(UTC)
    service, unit_of_work, _, _ = make_service(user=owner)

    async def fail_sending(**_message):
        raise RuntimeError("private gateway error")

    service.email_service.send_account_restored_notice = fail_sending
    await service.cancel_account_deletion(
        owner.id,
        SecretStr("correct horse battery staple"),
    )

    assert owner.deletion_requested_at is None
    assert unit_of_work.commits == 1


def test_account_recovery_period_is_30_days():
    assert DELETION_GRACE_PERIOD == timedelta(days=30)


@pytest.mark.asyncio
async def test_account_deletion_scrubs_owned_reminder_push_identifiers():
    user_id = uuid4()
    now = datetime.now(UTC)
    reminder = SimpleNamespace(
        created_by_user_id=user_id,
        expo_push_token="ExpoPushToken[private_device_token]",
        delivery_channel="push",
    )
    pending_push = SimpleNamespace(
        created_by_user_id=user_id,
        event_type="reminder.push",
        payload={"reminder_id": "id", "expo_push_token": "private-token"},
        processed_at=None,
        failed_at=None,
        last_error="stale",
    )
    due_event = SimpleNamespace(
        created_by_user_id=user_id,
        event_type="reminder.due",
        payload={"title": "Feed chickens", "expo_push_token": "private-token"},
        processed_at=None,
        failed_at=None,
        last_error=None,
    )

    class Session:
        async def scalars(self, statement):
            query = str(statement).lower()
            return FakeScalars(
                [reminder]
                if "from reminders" in query
                else [pending_push, due_event]
            )

    await DataDeletionService._scrub_user_specific_records(
        Session(),
        SimpleNamespace(id=user_id),
        now,
    )

    assert reminder.expo_push_token is None
    assert reminder.delivery_channel == "in_app"
    assert "expo_push_token" not in pending_push.payload
    assert pending_push.processed_at == now
    assert pending_push.last_error is None
    assert "expo_push_token" not in due_event.payload
    assert due_event.payload["title"] == "Feed chickens"


@pytest.mark.asyncio
async def test_failed_logo_cleanup_is_persisted_for_retry():
    now = datetime.now(UTC)
    job = SimpleNamespace(
        logo_path="/media/farm-logos/farm/logo.png",
        attempts=0,
        available_at=now,
        created_at=now,
        id=uuid4(),
        last_error_type=None,
    )
    deleted = []

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Session:
        def begin(self):
            return Transaction()

        async def scalars(self, _statement):
            return FakeScalars([job])

        async def delete(self, item):
            deleted.append(item)

    class Storage:
        def __init__(self):
            self.fail = True

        def delete(self, _logo_path):
            if self.fail:
                raise PermissionError("filesystem unavailable")

    storage = Storage()
    session = Session()

    assert await DataDeletionService.process_pending_logo_cleanup(
        session,
        storage,
        now,
    ) == 0
    assert job.attempts == 1
    assert job.available_at > now
    assert job.last_error_type == "PermissionError"
    assert deleted == []

    storage.fail = False
    assert await DataDeletionService.process_pending_logo_cleanup(
        session,
        storage,
        job.available_at,
    ) == 1
    assert deleted == [job]

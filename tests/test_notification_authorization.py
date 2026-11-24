from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.notifications import router
from app.dependencies.auth import get_current_user
from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_notification_service
from app.schemas.enums import NotificationCategory, NotificationPriority
from app.services.notification_service import NotificationService


class UnitOfWorkStub:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def flush(self):
        return None

    async def commit(self):
        return None


class NotificationRepositoryStub:
    def __init__(self, notification):
        self.notification = notification
        self.calls = []

    async def list_for_recipient(self, **kwargs):
        self.calls.append(kwargs)
        return []

    async def count_unread(self, **kwargs):
        self.calls.append(kwargs)
        return 0

    async def mark_all_read(self, **kwargs):
        self.calls.append(kwargs)
        return 0

    async def get_for_recipient(self, **kwargs):
        self.calls.append(kwargs)
        return self.notification


def test_notification_routes_scope_all_operations_to_authenticated_user():
    farm_id = uuid4()
    owner_id = uuid4()
    member_id = uuid4()
    notification_id = uuid4()
    now = datetime.now(UTC)
    farm = SimpleNamespace(id=farm_id, owner_id=owner_id)
    member = SimpleNamespace(id=member_id)
    notification = SimpleNamespace(
        id=notification_id,
        farm_id=farm_id,
        recipient_user_id=member_id,
        source_event_id=uuid4(),
        type="reminder.due",
        category=NotificationCategory.REMINDER,
        priority=NotificationPriority.NORMAL,
        title="Reminder due",
        message="A reminder is due.",
        entity_type="reminder",
        entity_id=uuid4(),
        payload=None,
        created_at=now,
        read_at=None,
        archived_at=None,
        expires_at=None,
    )
    repository = NotificationRepositoryStub(notification)
    service = NotificationService(repository, UnitOfWorkStub())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_owned_farm] = lambda: farm
    app.dependency_overrides[get_current_user] = lambda: member
    app.dependency_overrides[get_notification_service] = lambda: service

    with TestClient(app) as client:
        responses = [
            client.get(f"/farms/{farm_id}/notifications"),
            client.get(f"/farms/{farm_id}/notifications/unread-count"),
            client.patch(f"/farms/{farm_id}/notifications/read-all"),
            client.patch(
                f"/farms/{farm_id}/notifications/{notification_id}/read"
            ),
            client.patch(
                f"/farms/{farm_id}/notifications/{notification_id}/archive"
            ),
        ]

    assert [response.status_code for response in responses] == [200] * 5
    assert len(repository.calls) == 5
    assert all(call["farm_id"] == farm_id for call in repository.calls)
    assert all(
        call["recipient_user_id"] == member_id
        for call in repository.calls
    )
    assert all(
        call["recipient_user_id"] != owner_id
        for call in repository.calls
    )

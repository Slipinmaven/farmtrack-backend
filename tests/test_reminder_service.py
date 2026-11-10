import asyncio
import unittest
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4
from unittest.mock import patch

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.schemas.enums import ReminderStatus
from app.schemas.reminder import ReminderCreateRequest, ReminderRescheduleRequest
from app.services.reminder_service import ReminderService, enqueue_due_reminder_notifications


def _as_any(value: object) -> Any:
    return cast(Any, value)


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def flush(self):
        pass

    async def commit(self):
        pass


class FakeReminderRepository:
    def __init__(self):
        self.reminders = []

    async def create(self, farm_id, data):
        reminder = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            created_at=datetime.now(UTC),
            completed_at=None,
            notification_enqueued_at=None,
            **data,
        )
        self.reminders.append(reminder)
        return reminder

    async def list_by_farm(self, farm_id):
        return [reminder for reminder in self.reminders if reminder.farm_id == farm_id]

    async def get_by_id_for_farm(self, farm_id, reminder_id, *, for_update=False):
        return next(
            (
                reminder
                for reminder in self.reminders
                if reminder.farm_id == farm_id and reminder.id == reminder_id
            ),
            None,
        )


class FakeFarmSettingsRepository:
    async def get_farm_settings(self, _farm_id):
        return SimpleNamespace(timezone="Pacific/Kiritimati")


class ReminderServiceTests(unittest.TestCase):
    def test_get_reminder_is_limited_to_the_requested_farm(self):
        farm_id = uuid4()
        reminder_farm_id = uuid4()
        reminder = SimpleNamespace(
            id=uuid4(),
            farm_id=reminder_farm_id,
            title="Inspect the brooder",
            description="Check the heat lamp.",
            due_at=datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
            delivery_channel="in_app",
            status=ReminderStatus.PENDING.value,
            recurrence_rule=None,
            related_entity_type=None,
            related_entity_id=None,
            created_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
            completed_at=None,
            notification_enqueued_at=None,
        )
        repository = FakeReminderRepository()
        repository.reminders.append(reminder)
        service = ReminderService(
            _as_any(repository),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )

        with self.assertRaisesRegex(ResourceNotFoundError, "Reminder not found"):
            asyncio.run(
                service.get_for_farm(
                    _as_any(SimpleNamespace(id=farm_id)),
                    reminder.id,
                )
            )

        result = asyncio.run(
            service.get_for_farm(
                _as_any(SimpleNamespace(id=reminder_farm_id)),
                reminder.id,
            )
        )
        self.assertEqual(result.title, reminder.title)

    def test_local_due_time_is_converted_using_farm_timezone(self):
        farm = SimpleNamespace(id=uuid4())
        repository = FakeReminderRepository()
        service = ReminderService(
            _as_any(repository),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )
        request = ReminderCreateRequest(
            title="Pay chicken purchase balance",
            due_at=datetime(2026, 10, 13, 9, 0),
            related_entity_type="transaction",
            related_entity_id=uuid4(),
        )
        now = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
        with patch("app.services.reminder_service.datetime") as clock:
            clock.now.return_value = now
            clock.UTC = UTC
            result = asyncio.run(service.create(_as_any(farm), request))

        self.assertEqual(result.due_at, datetime(2026, 10, 12, 19, 0, tzinfo=UTC))
        self.assertEqual(result.status, ReminderStatus.PENDING)

    def test_push_reminder_requires_and_persists_a_valid_expo_token(self):
        farm = SimpleNamespace(id=uuid4())
        repository = FakeReminderRepository()
        service = ReminderService(
            _as_any(repository),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )
        due_at = datetime.now(UTC) + timedelta(days=1)
        request = ReminderCreateRequest(
            title="Push reminder",
            due_at=due_at,
            delivery_channel="push",
            expo_push_token="ExpoPushToken[device_token_123]",
        )

        result = asyncio.run(service.create(_as_any(farm), request))

        self.assertEqual(result.delivery_channel, "push")
        self.assertEqual(repository.reminders[0].expo_push_token, request.expo_push_token)

    def test_push_reminder_without_token_is_rejected(self):
        service = ReminderService(
            _as_any(FakeReminderRepository()),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )
        request = ReminderCreateRequest(
            title="Push reminder",
            due_at=datetime.now(UTC) + timedelta(days=1),
            delivery_channel="push",
        )

        with self.assertRaisesRegex(ConflictError, "push token is required"):
            asyncio.run(service.create(_as_any(SimpleNamespace(id=uuid4())), request))

    def test_pending_reminder_can_be_rescheduled_in_farm_timezone(self):
        farm_id = uuid4()
        reminder = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            title="Pay purchase balance",
            description="Follow up with supplier.",
            due_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
            delivery_channel="in_app",
            status=ReminderStatus.PENDING.value,
            recurrence_rule=None,
            related_entity_type="transaction",
            related_entity_id=uuid4(),
            created_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
            completed_at=None,
            notification_enqueued_at=None,
        )
        repository = FakeReminderRepository()
        repository.reminders.append(reminder)
        service = ReminderService(
            _as_any(repository),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )
        request = ReminderRescheduleRequest(due_at=datetime(2026, 10, 14, 10, 30))
        now = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
        with patch("app.services.reminder_service.datetime") as clock:
            clock.now.return_value = now
            clock.UTC = UTC
            result = asyncio.run(service.reschedule(
                _as_any(SimpleNamespace(id=farm_id)),
                reminder.id,
                request,
            ))

        self.assertEqual(result.due_at, datetime(2026, 10, 13, 20, 30, tzinfo=UTC))
        self.assertIsNone(reminder.notification_enqueued_at)

    def test_sent_pending_reminder_can_be_snoozed_again(self):
        farm_id = uuid4()
        reminder = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            title="Pay purchase balance",
            description="Follow up",
            due_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
            delivery_channel="in_app",
            status=ReminderStatus.PENDING.value,
            recurrence_rule=None,
            related_entity_type="transaction",
            related_entity_id=uuid4(),
            created_at=datetime.now(UTC),
            completed_at=None,
            notification_enqueued_at=datetime.now(UTC),
        )
        repository = FakeReminderRepository()
        repository.reminders.append(reminder)
        service = ReminderService(
            _as_any(repository),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )

        now = datetime.now(UTC)
        with patch("app.services.reminder_service.datetime") as clock:
            clock.now.return_value = now
            clock.UTC = UTC
            result = asyncio.run(service.reschedule(
                _as_any(SimpleNamespace(id=farm_id)),
                reminder.id,
                ReminderRescheduleRequest(due_at=now + timedelta(days=1)),
            ))
        self.assertEqual(result.status, ReminderStatus.PENDING)
        self.assertIsNone(reminder.notification_enqueued_at)

    def test_completed_reminder_can_be_reopened(self):
        farm_id = uuid4()
        reminder = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            title="Pay purchase balance",
            description="Follow up",
            due_at=datetime.now(UTC) + timedelta(days=1),
            delivery_channel="in_app",
            status=ReminderStatus.COMPLETED.value,
            recurrence_rule=None,
            related_entity_type="transaction",
            related_entity_id=uuid4(),
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            notification_enqueued_at=datetime.now(UTC),
        )
        repository = FakeReminderRepository()
        repository.reminders.append(reminder)
        service = ReminderService(
            _as_any(repository),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )

        result = asyncio.run(service.reopen(
            _as_any(SimpleNamespace(id=farm_id)),
            reminder.id,
        ))

        self.assertEqual(result.status, ReminderStatus.PENDING)
        self.assertIsNone(reminder.completed_at)
        self.assertIsNone(reminder.notification_enqueued_at)

    def test_recurring_reminders_are_explicitly_rejected(self):
        service = ReminderService(
            _as_any(FakeReminderRepository()),
            _as_any(FakeUnitOfWork()),
            _as_any(FakeFarmSettingsRepository()),
        )
        request = ReminderCreateRequest(
            title="Recurring task",
            due_at=datetime(2026, 10, 13, 9, 0),
            recurrence_rule={"frequency": "weekly"},
        )

        with self.assertRaises(ConflictError):
            asyncio.run(service.create(_as_any(SimpleNamespace(id=uuid4())), request))

    def test_due_reminder_outbox_key_is_stable(self):
        reminder = SimpleNamespace(
            id=uuid4(),
            farm_id=uuid4(),
            title="Pay balance",
            description="Purchase PUR-20261012-0001",
            due_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
            related_entity_type="transaction",
            related_entity_id=uuid4(),
        )
        queued = []

        class FakeRepository:
            async def list_due_pending(self, **_kwargs):
                return [reminder]

        class FakeOutbox:
            def __init__(self, _session):
                pass

            async def enqueue(self, **event):
                queued.append(event)

        class FakeSession:
            commits = 0

            async def commit(self):
                self.commits += 1

        session = FakeSession()

        with (
            patch(
                "app.services.reminder_service.ReminderRepository",
                return_value=FakeRepository(),
            ),
            patch(
                "app.services.reminder_service.NotificationOutboxRepository",
                FakeOutbox,
            ),
        ):
            count = asyncio.run(enqueue_due_reminder_notifications(session))

        self.assertEqual(count, 1)
        self.assertEqual(queued[0]["event_type"], "reminder.due")
        self.assertEqual(
            queued[0]["dedupe_key"],
            f"reminder-due:{reminder.id}:{reminder.due_at.isoformat()}",
        )
        self.assertIsNotNone(reminder.notification_enqueued_at)
        self.assertEqual(session.commits, 1)

    def test_push_due_reminder_enqueues_in_app_and_push_events(self):
        reminder = SimpleNamespace(
            id=uuid4(),
            farm_id=uuid4(),
            title="Pay balance",
            description="Purchase PUR-20261012-0001",
            due_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
            related_entity_type="transaction",
            related_entity_id=uuid4(),
            delivery_channel="push",
            expo_push_token="ExpoPushToken[device_token_123]",
        )
        queued = []

        class FakeRepository:
            async def list_due_pending(self, **_kwargs):
                return [reminder]

        class FakeOutbox:
            def __init__(self, _session):
                pass

            async def enqueue(self, **event):
                queued.append(event)

        class FakeSession:
            async def commit(self):
                pass

        with (
            patch(
                "app.services.reminder_service.ReminderRepository",
                return_value=FakeRepository(),
            ),
            patch(
                "app.services.reminder_service.NotificationOutboxRepository",
                FakeOutbox,
            ),
        ):
            asyncio.run(enqueue_due_reminder_notifications(FakeSession()))

        self.assertEqual(
            [event["event_type"] for event in queued],
            ["reminder.due", "reminder.push"],
        )
        self.assertEqual(
            queued[1]["payload"]["expo_push_token"], reminder.expo_push_token
        )
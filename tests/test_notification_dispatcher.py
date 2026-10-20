import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.models.notifications import Notification
from app.schemas.enums import NotificationCategory, NotificationPriority
from app.services.notification_dispatcher import NotificationDispatcher


class Result:
    def scalar_one_or_none(self):
        return SimpleNamespace(owner_id=uuid4())


class Session:
    def __init__(self):
        self.rollbacks = 0
        self.commits = 0

    async def execute(self, statement):
        self.statement = statement
        return Result()

    async def rollback(self):
        self.rollbacks += 1

    async def commit(self):
        self.commits += 1


class FailingOutboxRepository:
    def __init__(self, session):
        self.session = session
        self.failure_recorded = False

    async def claim_one(self):
        return SimpleNamespace(
            id=uuid4(),
            event_type="reminder.push",
            payload={
                "reminder_id": str(uuid4()),
                "expo_push_token": "ExpoPushToken[test]",
            },
        )

    async def record_failure(self, *_args, **_kwargs):
        if self.session.rollbacks != 1:
            raise AssertionError("Failed transaction was not rolled back first.")
        self.failure_recorded = True


class NotificationDispatcherTests(unittest.TestCase):
    def test_notification_enums_match_postgresql_labels(self):
        self.assertEqual(
            Notification.__table__.c.category.type.enums,
            [category.value for category in NotificationCategory],
        )
        self.assertEqual(
            Notification.__table__.c.priority.type.enums,
            [priority.value for priority in NotificationPriority],
        )

    def test_due_reminder_maps_to_linked_reminder_notification(self):
        session = Session()
        dispatcher = NotificationDispatcher(session)
        farm_id = uuid4()
        reminder_id = uuid4()
        event = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            event_type="reminder.due",
            payload={
                "reminder_id": str(reminder_id),
                "title": "Pay chicken purchase balance",
                "description": "Balance due on reference PUR-20261012-0001",
                "due_at": datetime(2026, 10, 13, 6, 0, tzinfo=UTC).isoformat(),
                "related_entity_type": "transaction",
                "related_entity_id": str(uuid4()),
            },
        )

        notification = asyncio.run(dispatcher._build_notification(event))

        self.assertEqual(notification["farm_id"], farm_id)
        self.assertEqual(notification["category"], NotificationCategory.REMINDER)
        self.assertEqual(notification["priority"], NotificationPriority.NORMAL)
        self.assertEqual(notification["title"], "Pay chicken purchase balance")
        self.assertEqual(notification["entity_type"], "reminder")
        self.assertEqual(notification["entity_id"], reminder_id)
        self.assertIn("PUR-20261012-0001", notification["message"])

    def test_purchase_notification_explains_which_purchase_was_recorded(self):
        dispatcher = NotificationDispatcher(Session())
        transaction_id = uuid4()
        event = SimpleNamespace(
            id=uuid4(),
            farm_id=uuid4(),
            event_type="purchase.recorded",
            payload={
                "transaction_id": str(transaction_id),
                "reference_number": "PUR-20261014-0002",
                "contact_name": "Sunny Hatchery",
                "transaction_total": "1250.00",
                "currency": "KES",
                "items_summary": "50 × Pullets",
            },
        )

        notification = asyncio.run(dispatcher._build_notification(event))

        self.assertEqual(notification["title"], "PUR-20261014-0002 recorded")
        self.assertEqual(
            notification["message"],
            "PUR-20261014-0002 from Sunny Hatchery was recorded for KES 1250.00. Items: 50 × Pullets.",
        )
        self.assertEqual(notification["entity_id"], transaction_id)

    def test_dispatch_failure_rolls_back_before_persisting_retry(self):
        session = Session()
        dispatcher = NotificationDispatcher(session)
        outbox = FailingOutboxRepository(session)
        dispatcher.outbox_repository = outbox

        async def fail_push(*_args, **_kwargs):
            raise RuntimeError("Push service unavailable")

        with patch(
            "app.services.notification_dispatcher.asyncio.to_thread",
            side_effect=fail_push,
        ):
            processed = asyncio.run(dispatcher.dispatch_once())

        self.assertFalse(processed)
        self.assertTrue(outbox.failure_recorded)
        self.assertEqual(session.rollbacks, 1)
        self.assertEqual(session.commits, 1)
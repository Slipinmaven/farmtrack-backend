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
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value or SimpleNamespace(owner_id=uuid4())


class Session:
    def __init__(self, result=None):
        self.rollbacks = 0
        self.commits = 0
        self.result = result or Result()
        self.loaded_membership = None

    async def execute(self, statement):
        self.statement = statement
        return self.result

    async def get(self, _model, _membership_id, with_for_update=False):
        return self.loaded_membership

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


class InvitationOutboxRepository:
    def __init__(self, *, event_id, membership_id):
        self.event_id = event_id
        self.membership_id = membership_id

    async def claim_one(self):
        return SimpleNamespace(
            id=self.event_id,
            event_type="farm.invitation.email",
            payload={"membership_id": str(self.membership_id)},
            processed_at=None,
            last_error=None,
        )

    async def record_failure(self, *_args, **_kwargs):
        return True


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

    def test_invitation_email_dispatch_marks_delivery_sent(self):
        membership = SimpleNamespace(
            status="invited",
            invitation_email_status="queued",
            invitation_email_sent_at=None,
        )
        session = Session(result=Result(membership))
        dispatcher = NotificationDispatcher(session)
        event_id = uuid4()
        dispatcher.outbox_repository = InvitationOutboxRepository(
            event_id=event_id,
            membership_id=uuid4(),
        )

        async def send_invitation(**_kwargs):
            return None

        dispatcher.smtp_email_service = SimpleNamespace(
            send_farm_invitation=send_invitation
        )

        processed = asyncio.run(dispatcher.dispatch_once())

        self.assertTrue(processed)
        self.assertEqual(membership.invitation_email_status, "sent")
        self.assertIsNotNone(membership.invitation_email_sent_at)
        self.assertEqual(session.commits, 1)

    def test_invitation_email_retry_exhaustion_marks_delivery_failed(self):
        membership_id = uuid4()
        membership = SimpleNamespace(
            status="invited",
            invitation_email_status="queued",
            invitation_email_sent_at=None,
        )
        session = Session(result=Result(membership))
        session.loaded_membership = membership
        dispatcher = NotificationDispatcher(session)
        dispatcher.outbox_repository = InvitationOutboxRepository(
            event_id=uuid4(),
            membership_id=membership_id,
        )
        event_id = uuid4()

        async def claim_one():
            return SimpleNamespace(
                id=event_id,
                event_type="farm.invitation.email",
                payload={"membership_id": str(membership_id)},
                processed_at=None,
                last_error=None,
            )

        dispatcher.outbox_repository.claim_one = claim_one

        async def fail_sending(**_kwargs):
            raise RuntimeError("Gmail SMTP unavailable")

        dispatcher.smtp_email_service = SimpleNamespace(
            send_farm_invitation=fail_sending
        )

        processed = asyncio.run(dispatcher.dispatch_once())

        self.assertFalse(processed)
        self.assertEqual(membership.invitation_email_status, "failed")
        self.assertEqual(session.rollbacks, 1)
        self.assertEqual(session.commits, 1)
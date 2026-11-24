from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.email_gateway_service import FarmTrackEmailService
from app.core.logging import get_application_logger
from app.models.farm import Farm
from app.models.farm_membership import FarmMembership
from app.models.notifications import Notification
from app.models.notification_outbox import NotificationOutbox
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.repositories.notification_repository import NotificationRepository
from app.schemas.enums import NotificationCategory, NotificationPriority
from app.services.expo_push import send_expo_push_notification

logger = get_application_logger()


class NotificationDispatcher:
    def __init__(
        self,
        session: AsyncSession,
        *,
        email_service: FarmTrackEmailService | None = None,
    ) -> None:
        self.session = session
        self.outbox_repository = NotificationOutboxRepository(session)
        self.notification_repository = NotificationRepository(session)
        self.email_service = email_service or FarmTrackEmailService()

    async def dispatch_once(self, *, max_attempts: int = 5) -> bool:
        event = await self.outbox_repository.claim_one()
        if event is None:
            return False
        event_id = event.id
        event_type = event.event_type
        payload = event.payload or {}
        try:
            if event_type == "reminder.push":
                await asyncio.to_thread(
                    send_expo_push_notification,
                    str(payload["expo_push_token"]),
                    str(payload.get("title") or "Reminder due"),
                    str(payload.get("description") or payload.get("title") or "Reminder due"),
                    {"reminder_id": str(payload["reminder_id"])},
                )
            elif event_type == "farm.invitation.email":
                await self._send_farm_invitation_email(event_id, payload)
            else:
                notification = await self._build_notification(event)
                await self.notification_repository.create_for_source_event(notification)
            event.processed_at = datetime.now(timezone.utc)
            event.last_error = None
            await self.session.commit()
            return True
        except Exception as exc:  # pragma: no cover - worker failure path
            error_summary = f"{type(exc).__name__}: {exc}"
            await self.session.rollback()
            logger.exception(
                "notification_dispatch_failed",
                extra={
                    "event": "notification_dispatch_failed",
                    "outbox_id": str(event_id),
                    "event_type": event_type,
                    "error": error_summary,
                },
            )
            try:
                terminal_failure = await self.outbox_repository.record_failure(
                    event_id,
                    now=datetime.now(timezone.utc),
                    max_attempts=max_attempts,
                    error_summary=error_summary,
                )
                if terminal_failure and event_type == "farm.invitation.email":
                    membership_id = UUID(str(payload["membership_id"]))
                    membership = await self.session.get(
                        FarmMembership,
                        membership_id,
                        with_for_update=True,
                    )
                    if membership is not None:
                        membership.invitation_email_status = "failed"
                await self.session.commit()
            except Exception:
                await self.session.rollback()
                logger.exception(
                    "notification_failure_recording_failed",
                    extra={
                        "event": "notification_failure_recording_failed",
                        "outbox_id": str(event_id),
                        "event_type": event_type,
                    },
                )
            return False

    async def _send_farm_invitation_email(
        self,
        outbox_id: UUID,
        payload: dict,
    ) -> None:
        membership_id = UUID(str(payload["membership_id"]))
        result = await self.session.execute(
            select(FarmMembership)
            .options(
                selectinload(FarmMembership.user),
                selectinload(FarmMembership.farm),
            )
            .where(FarmMembership.id == membership_id)
            .with_for_update()
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            return
        if membership.status != "invited":
            membership.invitation_email_status = "cancelled"
            return

        await self.email_service.send_farm_invitation(
            membership=membership,
            idempotency_key=outbox_id,
        )
        membership.invitation_email_status = "sent"
        membership.invitation_email_sent_at = datetime.now(timezone.utc)

    async def _build_notification(self, event: NotificationOutbox) -> dict:
        event_type = event.event_type
        payload = event.payload or {}
        farm_result = await self.session.execute(select(Farm).where(Farm.id == event.farm_id))
        farm = farm_result.scalar_one_or_none()
        if farm is None:
            raise ValueError(f"Farm {event.farm_id} for notification event was not found.")
        recipient_user_id = farm.owner_id
        if event_type == "purchase.recorded":
            transaction_id = UUID(payload["transaction_id"])
            purchase_reference = str(payload.get("reference_number") or "Purchase")
            supplier = str(payload.get("contact_name") or "supplier")
            total = payload.get("transaction_total")
            currency = payload.get("currency")
            items_summary = str(payload.get("items_summary") or "").strip()
            total_text = (
                f" for {currency} {total}"
                if total is not None and currency
                else f" with a total of {total}"
                if total is not None
                else ""
            )
            return {
                "farm_id": event.farm_id,
                "recipient_user_id": recipient_user_id,
                "source_event_id": event.id,
                "type": event_type,
                "category": NotificationCategory.TRANSACTION,
                "priority": NotificationPriority.NORMAL,
                "title": f"{purchase_reference} recorded",
                "message": (
                    f"{purchase_reference} from {supplier} was recorded{total_text}."
                    + (f" Items: {items_summary}." if items_summary else "")
                )[:500],
                "entity_type": "transaction",
                "entity_id": transaction_id,
                "payload": payload,
                "created_at": datetime.now(timezone.utc),
                "read_at": None,
                "archived_at": None,
                "expires_at": None,
            }
        if event_type == "sale.recorded":
            transaction_id = UUID(payload["transaction_id"])
            sale_reference = str(payload.get("reference_number") or "Sale")
            customer = str(payload.get("contact_name") or "customer")
            total = payload.get("transaction_total")
            currency = payload.get("currency")
            items_summary = str(payload.get("items_summary") or "").strip()
            total_text = (
                f" for {currency} {total}"
                if total is not None and currency
                else f" with a total of {total}"
                if total is not None
                else ""
            )
            return {
                "farm_id": event.farm_id,
                "recipient_user_id": recipient_user_id,
                "source_event_id": event.id,
                "type": event_type,
                "category": NotificationCategory.TRANSACTION,
                "priority": NotificationPriority.NORMAL,
                "title": f"{sale_reference} recorded",
                "message": (
                    f"{sale_reference} to {customer} was recorded{total_text}."
                    + (f" Items: {items_summary}." if items_summary else "")
                )[:500],
                "entity_type": "transaction",
                "entity_id": transaction_id,
                "payload": payload,
                "created_at": datetime.now(timezone.utc),
                "read_at": None,
                "archived_at": None,
                "expires_at": None,
            }
        if event_type == "payment.recorded":
            transaction_id = UUID(payload["transaction_id"])
            payment_amount = payload.get("payment_amount")
            payment_currency = payload.get("currency")
            amount_text = (
                f" of {payment_currency} {payment_amount}"
                if payment_amount is not None and payment_currency
                else f" of {payment_amount}"
                if payment_amount is not None
                else ""
            )
            reference = payload.get("reference_number")
            return {
                "farm_id": event.farm_id,
                "recipient_user_id": recipient_user_id,
                "source_event_id": event.id,
                "type": event_type,
                "category": NotificationCategory.TRANSACTION,
                "priority": NotificationPriority.NORMAL,
                "title": (
                    "Payment received"
                    if payload.get("transaction_type") == "sale"
                    else "Payment to supplier recorded"
                ),
                "message": (
                    f"Payment{amount_text} recorded"
                    + (f" for {reference}" if reference else "")
                    + "."
                ),
                "entity_type": "transaction",
                "entity_id": transaction_id,
                "payload": payload,
                "created_at": datetime.now(timezone.utc),
                "read_at": None,
                "archived_at": None,
                "expires_at": None,
            }
        if event_type == "chicken_return.recorded":
            return_id = UUID(payload["return_id"])
            return {
                "farm_id": event.farm_id,
                "recipient_user_id": recipient_user_id,
                "source_event_id": event.id,
                "type": event_type,
                "category": NotificationCategory.TRANSACTION,
                "priority": NotificationPriority.NORMAL,
                "title": "Chicken return recorded",
                "message": "A chicken return was recorded successfully.",
                "entity_type": "sale_return",
                "entity_id": return_id,
                "payload": payload,
                "created_at": datetime.now(timezone.utc),
                "read_at": None,
                "archived_at": None,
                "expires_at": None,
            }
        if event_type == "chicken_movement.recorded":
            movement_id = UUID(payload["movement_id"])
            return {
                "farm_id": event.farm_id,
                "recipient_user_id": recipient_user_id,
                "source_event_id": event.id,
                "type": event_type,
                "category": NotificationCategory.FARM,
                "priority": NotificationPriority.NORMAL,
                "title": "Chicken movement recorded",
                "message": "A chicken movement was recorded successfully.",
                "entity_type": "chicken_movement",
                "entity_id": movement_id,
                "payload": payload,
                "created_at": datetime.now(timezone.utc),
                "read_at": None,
                "archived_at": None,
                "expires_at": None,
            }
        if event_type == "reminder.due":
            reminder_id = UUID(payload["reminder_id"])
            title = str(payload.get("title") or "Reminder due")
            description = str(payload.get("description") or "")
            message = description or f"{title} is due."
            return {
                "farm_id": event.farm_id,
                "recipient_user_id": recipient_user_id,
                "source_event_id": event.id,
                "type": event_type,
                "category": NotificationCategory.REMINDER,
                "priority": NotificationPriority.NORMAL,
                "title": title,
                "message": message[:500],
                "entity_type": "reminder",
                "entity_id": reminder_id,
                "payload": payload,
                "created_at": datetime.now(timezone.utc),
                "read_at": None,
                "archived_at": None,
                "expires_at": None,
            }
        raise ValueError(f"Unsupported notification event type: {event_type}")


async def process_pending_notifications(
    session: AsyncSession,
    *,
    batch_size: int = 20,
    email_service: FarmTrackEmailService | None = None,
) -> int:
    dispatcher = NotificationDispatcher(session, email_service=email_service)
    processed = 0
    for _ in range(batch_size):
        if not await dispatcher.dispatch_once():
            break
        processed += 1
    return processed

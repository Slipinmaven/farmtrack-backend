from datetime import UTC, datetime, timezone
import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.farm_settings_repository import FarmSettingsRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.repositories.reminder_repository import ReminderRepository
from app.schemas.enums import ReminderStatus
from app.schemas.reminder import ReminderCreateRequest, ReminderResponse


def _normalize_due_at(due_at: datetime, timezone_name: str | None) -> datetime:
    if due_at.tzinfo is not None:
        return due_at.astimezone(UTC)

    try:
        farm_timezone = ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError as exc:
        raise ConflictError("The farm timezone is invalid.") from exc

    local_due_at = due_at.replace(tzinfo=farm_timezone, fold=0)
    round_trip = (
        local_due_at.astimezone(UTC)
        .astimezone(farm_timezone)
        .replace(tzinfo=None)
    )
    if round_trip != due_at:
        raise ConflictError("That reminder time does not exist in the farm timezone.")
    return local_due_at.astimezone(UTC)


class ReminderService:
    def __init__(
        self,
        repository: ReminderRepository,
        unit_of_work: UnitOfWork,
        farm_settings_repository: FarmSettingsRepository,
    ):
        self.repository = repository
        self.unit_of_work = unit_of_work
        self.farm_settings_repository = farm_settings_repository

    async def create(
        self,
        farm: Farm,
        request: ReminderCreateRequest,
    ) -> ReminderResponse:
        if request.recurrence_rule is not None:
            raise ConflictError("Recurring reminders are not supported yet.")
        if request.delivery_channel == "push":
            if not request.expo_push_token or not re.fullmatch(
                r"(?:Expo|Exponent)PushToken\[[A-Za-z0-9_-]+\]",
                request.expo_push_token,
            ):
                raise ConflictError("A valid Expo push token is required for push reminders.")
        elif request.expo_push_token is not None:
            raise ConflictError("Push tokens are only allowed for push reminders.")

        async with self.unit_of_work:
            farm_settings = await self.farm_settings_repository.get_farm_settings(
                farm.id
            )
            due_at = _normalize_due_at(
                request.due_at,
                farm_settings.timezone if farm_settings else None,
            )
            if due_at <= datetime.now(UTC):
                raise ConflictError("Reminder due time must be in the future.")

            reminder = await self.repository.create(
                farm.id,
                {
                    "title": request.title.strip(),
                    "description": request.description.strip()
                    if request.description
                    else None,
                    "due_at": due_at,
                    "delivery_channel": request.delivery_channel,
                    "expo_push_token": request.expo_push_token,
                    "status": ReminderStatus.PENDING.value,
                    "recurrence_rule": None,
                    "related_entity_type": request.related_entity_type,
                    "related_entity_id": request.related_entity_id,
                },
            )
            await self.unit_of_work.commit()
            return ReminderResponse.model_validate(reminder, from_attributes=True)

    async def list_for_farm(self, farm: Farm) -> list[ReminderResponse]:
        async with self.unit_of_work:
            reminders = await self.repository.list_by_farm(farm.id)
            return [
                ReminderResponse.model_validate(reminder, from_attributes=True)
                for reminder in reminders
            ]

    async def get_for_farm(
        self,
        farm: Farm,
        reminder_id: UUID,
    ) -> ReminderResponse:
        async with self.unit_of_work:
            reminder = await self.repository.get_by_id_for_farm(
                farm.id,
                reminder_id,
            )
            if reminder is None:
                raise ResourceNotFoundError("Reminder not found.")
            return ReminderResponse.model_validate(reminder, from_attributes=True)

    async def update_status(
        self,
        farm: Farm,
        reminder_id,
        status: ReminderStatus,
    ) -> ReminderResponse:
        async with self.unit_of_work:
            reminder = await self.repository.get_by_id_for_farm(
                farm.id,
                reminder_id,
                for_update=True,
            )
            if reminder is None:
                raise ResourceNotFoundError("Reminder not found.")
            if reminder.status != ReminderStatus.PENDING.value:
                raise ConflictError("Only pending reminders can be changed.")

            reminder.status = status.value
            if status == ReminderStatus.COMPLETED:
                reminder.completed_at = datetime.now(timezone.utc)
            await self.unit_of_work.flush()
            await self.unit_of_work.commit()
            return ReminderResponse.model_validate(reminder, from_attributes=True)


async def enqueue_due_reminder_notifications(
    session,
    *,
    now: datetime | None = None,
    batch_size: int = 100,
) -> int:
    current_time = now or datetime.now(UTC)
    due_reminders = await ReminderRepository(session).list_due_pending(
        now=current_time,
        limit=batch_size,
    )
    outbox = NotificationOutboxRepository(session)
    for reminder in due_reminders:
        await outbox.enqueue(
            farm_id=reminder.farm_id,
            event_type="reminder.due",
            payload={
                "reminder_id": str(reminder.id),
                "title": reminder.title,
                "description": reminder.description,
                "due_at": reminder.due_at.isoformat(),
                "delivery_channel": getattr(reminder, "delivery_channel", "in_app"),
                "expo_push_token": getattr(reminder, "expo_push_token", None),
                "related_entity_type": reminder.related_entity_type,
                "related_entity_id": (
                    str(reminder.related_entity_id)
                    if reminder.related_entity_id
                    else None
                ),
            },
            dedupe_key=f"reminder-due:{reminder.id}:{reminder.due_at.isoformat()}",
        )
        delivery_channel = getattr(reminder, "delivery_channel", "in_app")
        expo_push_token = getattr(reminder, "expo_push_token", None)
        if delivery_channel == "push" and expo_push_token:
            await outbox.enqueue(
                farm_id=reminder.farm_id,
                event_type="reminder.push",
                payload={
                    "reminder_id": str(reminder.id),
                    "title": reminder.title,
                    "description": reminder.description,
                    "expo_push_token": expo_push_token,
                },
                dedupe_key=f"reminder-push:{reminder.id}:{reminder.due_at.isoformat()}",
            )
        reminder.notification_enqueued_at = current_time
    if due_reminders:
        await session.commit()
    return len(due_reminders)
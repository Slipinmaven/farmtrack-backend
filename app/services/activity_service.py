import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.exceptions import InvalidActivityCursorError, ResourceNotFoundError
from app.core.request_context import auth_session_id_context, auth_user_id_context
from app.core.unit_of_work import UnitOfWork
from app.models.activities import Activity
from app.models.farm import Farm
from app.repositories.activity_repository import ActivityRepository
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.schemas.activity import (
    ActivityFeedResponse,
    ActivityResponse,
    ActivitySummaryResponse,
)
from app.schemas.enums import ActivityCategory, ActivityEntityType, ActivityType
from app.services.activity_details import activity_value


class ActivityService:
    def __init__(
        self,
        repository: ActivityRepository,
        unit_of_work: UnitOfWork,
        user_session_repository: UserSessionRepository | None = None,
        egg_collection_repository: EggCollectionRepository | None = None,
    ):
        self.repository = repository
        self.unit_of_work = unit_of_work
        self.user_session_repository = user_session_repository
        self.egg_collection_repository = egg_collection_repository

    async def record(
        self,
        *,
        farm_id: UUID,
        user_id: UUID | None,
        activity_type: ActivityType,
        entity_type: ActivityEntityType,
        entity_id: UUID,
        details: dict[str, object] | None = None,
    ) -> Activity:
        activity = Activity(
            farm_id=farm_id,
            user_id=auth_user_id_context.get() or user_id,
            session_id=auth_session_id_context.get(),
            type=activity_type,
            entity_type=entity_type,
            entity_id=entity_id,
            details=self._sanitize_details(details),
        )
        return await self.repository.create(activity)

    @classmethod
    def _sanitize_details(
        cls, details: dict[str, object] | None
    ) -> dict[str, object] | None:
        if details is None:
            return None

        def sanitize(value: object) -> object:
            if isinstance(value, dict):
                field_name = value.get("field")
                if isinstance(field_name, str) and any(
                    sensitive in field_name.casefold()
                    for sensitive in (
                        "password",
                        "passphrase",
                        "secret",
                        "token",
                        "credential",
                    )
                ):
                    return {
                        "field": (
                            "password"
                            if "password" in field_name.casefold()
                            else "sensitive_setting"
                        ),
                        "changed": True,
                    }
                return {
                    str(key): sanitize(item)
                    for key, item in value.items()
                    if not any(
                        sensitive in str(key).casefold()
                        for sensitive in (
                            "password",
                            "passphrase",
                            "secret",
                            "token",
                            "credential",
                        )
                    )
                }
            if isinstance(value, (list, tuple)):
                return [sanitize(item) for item in value]
            return activity_value(value)

        sanitized = sanitize(details)
        if not isinstance(sanitized, dict):
            raise TypeError("Activity details must remain a JSON object.")
        return sanitized

    async def list_for_farm(
        self,
        farm: Farm,
        limit: int,
        before: str | None = None,
        search: str | None = None,
        category: ActivityCategory | None = None,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
    ) -> ActivityFeedResponse:
        cursor = self._decode_cursor(before) if before is not None else None
        async with self.unit_of_work:
            activities = await self.repository.list_for_farm(
                farm_id=farm.id,
                limit=limit + 1,
                before=cursor,
                search=search,
                category=category,
                from_datetime=from_datetime,
                to_datetime=to_datetime,
            )
            total_count = await self.repository.count_for_farm(
                farm_id=farm.id,
                search=search,
                category=category,
                from_datetime=from_datetime,
                to_datetime=to_datetime,
            )
            has_more = len(activities) > limit
            items = activities[:limit]
            next_cursor = self._encode_cursor(items[-1]) if has_more else None
            return ActivityFeedResponse(
                items=[
                    ActivityResponse.model_validate(activity, from_attributes=True)
                    for activity in items
                ],
                next_cursor=next_cursor,
                has_more=has_more,
                total_count=total_count,
            )

    async def get_for_farm(
        self, farm: Farm, activity_id: UUID
    ) -> ActivityResponse:
        async with self.unit_of_work:
            activity = await self.repository.get_by_id_for_farm(
                farm.id, activity_id
            )
            if activity is None:
                raise ResourceNotFoundError("Activity not found.")
            response = ActivityResponse.model_validate(
                activity,
                from_attributes=True,
            )
            if (
                activity.type != ActivityType.EGG_COLLECTION_RECORDED
                or self.egg_collection_repository is None
                or response.details is None
            ):
                return response

            raw_collection_ids = response.details.get("collection_ids")
            if not isinstance(raw_collection_ids, list):
                return response
            collection_ids_by_index = []
            for raw_id in raw_collection_ids:
                if not isinstance(raw_id, str):
                    collection_ids_by_index.append(None)
                    continue
                try:
                    collection_ids_by_index.append(UUID(raw_id))
                except ValueError:
                    collection_ids_by_index.append(None)
            collection_ids = [
                collection_id
                for collection_id in collection_ids_by_index
                if collection_id is not None
            ]
            if not collection_ids:
                return response

            units_by_collection = (
                await self.egg_collection_repository.get_units_by_collection_ids(
                    farm.id,
                    collection_ids,
                )
            )
            raw_items = response.details.get("items")
            if not isinstance(raw_items, list):
                return response

            details = dict(response.details)
            items = list(raw_items)
            for index, collection_id in enumerate(collection_ids_by_index):
                if index >= len(items) or not isinstance(items[index], dict):
                    continue
                if collection_id is None:
                    continue
                unit = units_by_collection.get(collection_id)
                if unit is None:
                    continue
                item = dict(items[index])
                if not item.get("unit_name"):
                    item["unit_name"] = unit[0]
                if not item.get("unit_abbreviation"):
                    item["unit_abbreviation"] = unit[1]
                items[index] = item
            details["items"] = items
            return response.model_copy(update={"details": details})

    async def get_summary_for_farm(
        self, farm: Farm
    ) -> ActivitySummaryResponse:
        now = datetime.now(UTC)
        current_period_start = now - timedelta(days=7)
        previous_period_start = now - timedelta(days=14)
        async with self.unit_of_work:
            counts = await self.repository.get_summary_for_farm(
                farm.id,
                now,
                current_period_start,
                previous_period_start,
            )
        return ActivitySummaryResponse(
            last_7_days_count=counts["last_7_days_count"],
            previous_7_days_count=counts["previous_7_days_count"],
            losses_and_returns_count=counts["losses_and_returns_count"],
            category_counts={
                category: counts[category.value] for category in ActivityCategory
            },
        )

    async def list_for_session(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        limit: int,
        before: str | None = None,
    ) -> ActivityFeedResponse:
        if self.user_session_repository is None:
            raise ResourceNotFoundError("Session activity was not found.")
        user_session = await self.user_session_repository.get_by_id(session_id)
        if user_session is None or user_session.user_id != user_id:
            raise ResourceNotFoundError("Session activity was not found.")

        cursor = self._decode_cursor(before) if before is not None else None
        async with self.unit_of_work:
            activities = await self.repository.list_for_session(
                session_id=session_id,
                limit=limit + 1,
                before=cursor,
            )
            has_more = len(activities) > limit
            items = activities[:limit]
            next_cursor = self._encode_cursor(items[-1]) if has_more else None
            return ActivityFeedResponse(
                items=[
                    ActivityResponse.model_validate(activity, from_attributes=True)
                    for activity in items
                ],
                next_cursor=next_cursor,
                has_more=has_more,
            )
            has_more = len(activities) > limit
            items = activities[:limit]
            next_cursor = self._encode_cursor(items[-1]) if has_more else None
            return ActivityFeedResponse(
                items=[
                    ActivityResponse.model_validate(activity, from_attributes=True)
                    for activity in items
                ],
                next_cursor=next_cursor,
                has_more=has_more,
            )

    @staticmethod
    def _encode_cursor(activity: Activity) -> str:
        payload = json.dumps(
            {"created_at": activity.created_at.isoformat(), "id": str(activity.id)},
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        try:
            padded_cursor = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded_cursor).decode("utf-8"))
            created_at = datetime.fromisoformat(payload["created_at"])
            activity_id = UUID(payload["id"])
            if created_at.tzinfo is None:
                raise ValueError("Cursor timestamp must include a timezone")
            return created_at, activity_id
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise InvalidActivityCursorError() from None
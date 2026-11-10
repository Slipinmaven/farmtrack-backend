import asyncio
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.dialects import postgresql

from app.core.exceptions import ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.activities import Activity
from app.models.farm import Farm
from app.repositories.activity_repository import ActivityRepository
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.schemas.enums import ActivityCategory, ActivityEntityType, ActivityType
from app.services.activity_details import activity_field_changes
from app.services.activity_service import ActivityService


class ActivityFeedTests(unittest.TestCase):
    def test_change_details_serialize_dates_and_decimal_values(self):
        changes = activity_field_changes(
            {
                "name": "Old farm name",
                "egg_price": Decimal("2.50"),
                "effective_date": date(2026, 1, 1),
            },
            {
                "name": "New farm name",
                "egg_price": Decimal("3.00"),
                "effective_date": date(2026, 2, 1),
            },
        )

        self.assertEqual(
            changes,
            [
                {"field": "name", "from": "Old farm name", "to": "New farm name"},
                {"field": "egg_price", "from": "2.50", "to": "3.00"},
                {
                    "field": "effective_date",
                    "from": "2026-01-01",
                    "to": "2026-02-01",
                },
            ],
        )

    def test_activity_details_sanitize_sensitive_fields_recursively(self):
        sanitized = ActivityService._sanitize_details(
            {
                "changes": [
                    {
                        "field": "password_hash",
                        "from": "old-hash",
                        "to": "new-hash",
                    },
                    {"field": "name", "from": "Old", "to": "New"},
                ],
                "items": [{"quantity": 2, "refresh_token": "private"}],
            }
        )

        self.assertEqual(
            sanitized,
            {
                "changes": [
                    {"field": "password", "changed": True},
                    {"field": "name", "from": "Old", "to": "New"},
                ],
                "items": [{"quantity": 2}],
            },
        )
        self.assertNotIn("old-hash", repr(sanitized))
        self.assertNotIn("new-hash", repr(sanitized))

    def test_farm_feed_builds_cursor_and_passes_filters(self):
        farm_id = uuid4()
        range_start = datetime(2026, 10, 1, tzinfo=UTC)
        range_end = datetime(2026, 11, 1, tzinfo=UTC)
        activities = [
            Activity(
                id=uuid4(),
                farm_id=farm_id,
                user_id=None,
                session_id=None,
                type=ActivityType.EGG_COLLECTION_RECORDED,
                entity_type=ActivityEntityType.EGG_COLLECTION,
                entity_id=uuid4(),
                details={"quantity": 12},
                created_at=datetime.now(UTC) - timedelta(minutes=index),
            )
            for index in range(2)
        ]

        class UnitOfWorkStub:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        class RepositoryStub:
            kwargs: dict[str, object] | None = None

            async def list_for_farm(self, **kwargs: object) -> list[Activity]:
                self.kwargs = kwargs
                return activities

            async def count_for_farm(self, **kwargs: object) -> int:
                self.count_kwargs = kwargs
                return 3

        repository = RepositoryStub()
        service = ActivityService(
            cast(ActivityRepository, repository),
            cast(UnitOfWork, UnitOfWorkStub()),
        )

        response = asyncio.run(
            service.list_for_farm(
                cast(Farm, SimpleNamespace(id=farm_id)),
                limit=1,
                search="twelve eggs",
                category=ActivityCategory.EGGS,
                from_datetime=range_start,
                to_datetime=range_end,
            )
        )

        self.assertEqual(len(response.items), 1)
        self.assertTrue(response.has_more)
        self.assertIsNotNone(response.next_cursor)
        self.assertEqual(response.total_count, 3)
        assert repository.kwargs is not None
        self.assertEqual(repository.kwargs["limit"], 2)
        self.assertEqual(repository.kwargs["search"], "twelve eggs")
        self.assertEqual(repository.kwargs["category"], ActivityCategory.EGGS)
        self.assertEqual(repository.kwargs["from_datetime"], range_start)
        self.assertEqual(repository.kwargs["to_datetime"], range_end)
        assert repository.count_kwargs is not None
        self.assertEqual(repository.count_kwargs["farm_id"], farm_id)
        self.assertEqual(repository.count_kwargs["search"], "twelve eggs")
        self.assertEqual(repository.count_kwargs["category"], ActivityCategory.EGGS)
        self.assertEqual(repository.count_kwargs["from_datetime"], range_start)
        self.assertEqual(repository.count_kwargs["to_datetime"], range_end)

    def test_get_activity_is_scoped_to_the_selected_farm(self):
        farm_id = uuid4()
        activity = Activity(
            id=uuid4(),
            farm_id=farm_id,
            user_id=None,
            session_id=None,
            type=ActivityType.EGG_COLLECTION_RECORDED,
            entity_type=ActivityEntityType.EGG_COLLECTION,
            entity_id=uuid4(),
            details={"entry_count": 3},
            created_at=datetime.now(UTC),
        )

        class UnitOfWorkStub:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        class RepositoryStub:
            requested_ids: tuple[UUID, UUID] | None = None

            async def get_by_id_for_farm(
                self, requested_farm_id: UUID, activity_id: UUID
            ) -> Activity | None:
                self.requested_ids = (requested_farm_id, activity_id)
                return activity if requested_farm_id == farm_id else None

        repository = RepositoryStub()
        service = ActivityService(
            cast(ActivityRepository, repository),
            cast(UnitOfWork, UnitOfWorkStub()),
        )
        farm = cast(Farm, SimpleNamespace(id=farm_id))

        response = asyncio.run(service.get_for_farm(farm, activity.id))

        self.assertEqual(response.id, activity.id)
        self.assertEqual(repository.requested_ids, (farm_id, activity.id))

        with self.assertRaises(ResourceNotFoundError):
            asyncio.run(
                service.get_for_farm(
                    cast(Farm, SimpleNamespace(id=uuid4())), activity.id
                )
            )

    def test_egg_collection_detail_recovers_units_for_legacy_activity(self):
        farm_id = uuid4()
        collection_id = uuid4()
        activity = Activity(
            id=uuid4(),
            farm_id=farm_id,
            user_id=None,
            session_id=None,
            type=ActivityType.EGG_COLLECTION_RECORDED,
            entity_type=ActivityEntityType.EGG_COLLECTION,
            entity_id=collection_id,
            details={
                "collection_ids": [str(collection_id)],
                "items": [{"product_name": "Eggs", "quantity": "10"}],
            },
            created_at=datetime.now(UTC),
        )

        class UnitOfWorkStub:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        class ActivityRepositoryStub:
            async def get_by_id_for_farm(
                self, requested_farm_id: UUID, activity_id: UUID
            ) -> Activity | None:
                return activity if requested_farm_id == farm_id else None

        class EggCollectionRepositoryStub:
            async def get_units_by_collection_ids(
                self,
                requested_farm_id: UUID,
                collection_ids: list[UUID],
            ) -> dict[UUID, tuple[str, str]]:
                self.requested_ids = (requested_farm_id, collection_ids)
                return {collection_id: ("tray", "tray")}

        egg_repository = EggCollectionRepositoryStub()
        service = ActivityService(
            cast(ActivityRepository, ActivityRepositoryStub()),
            cast(UnitOfWork, UnitOfWorkStub()),
            egg_collection_repository=cast(
                EggCollectionRepository,
                egg_repository,
            ),
        )
        response = asyncio.run(
            service.get_for_farm(
                cast(Farm, SimpleNamespace(id=farm_id)),
                activity.id,
            )
        )

        assert response.details is not None
        self.assertEqual(response.details["items"][0]["unit_name"], "tray")
        self.assertEqual(
            response.details["items"][0]["unit_abbreviation"],
            "tray",
        )
        self.assertEqual(egg_repository.requested_ids, (farm_id, [collection_id]))

    def test_summary_returns_period_counts_and_all_categories(self):
        farm_id = uuid4()
        expected = {
            "last_7_days_count": 8,
            "previous_7_days_count": 5,
            "losses_and_returns_count": 2,
            **{category.value: index for index, category in enumerate(ActivityCategory)},
        }

        class UnitOfWorkStub:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        class RepositoryStub:
            async def get_summary_for_farm(
                self,
                requested_farm_id: UUID,
                period_end: datetime,
                current_period_start: datetime,
                previous_period_start: datetime,
            ) -> dict[str, int]:
                self.requested_farm_id = requested_farm_id
                self.period_end = period_end
                self.current_period_start = current_period_start
                self.previous_period_start = previous_period_start
                return expected

        repository = RepositoryStub()
        service = ActivityService(
            cast(ActivityRepository, repository),
            cast(UnitOfWork, UnitOfWorkStub()),
        )

        response = asyncio.run(
            service.get_summary_for_farm(cast(Farm, SimpleNamespace(id=farm_id)))
        )

        self.assertEqual(response.last_7_days_count, 8)
        self.assertEqual(response.previous_7_days_count, 5)
        self.assertEqual(response.losses_and_returns_count, 2)
        self.assertEqual(
            response.category_counts[ActivityCategory.EGGS],
            expected[ActivityCategory.EGGS.value],
        )
        self.assertLess(repository.previous_period_start, repository.current_period_start)
        self.assertLess(repository.current_period_start, repository.period_end)

    def test_summary_repository_builds_postgres_query_for_all_categories(self):
        expected = {
            "last_7_days_count": 3,
            "previous_7_days_count": 4,
            "losses_and_returns_count": 1,
            **{category.value: 0 for category in ActivityCategory},
        }

        class ResultStub:
            def one(self):
                return SimpleNamespace(_mapping=expected)

        class SessionStub:
            statement: str | None = None

            async def execute(self, statement):
                self.statement = str(statement.compile(dialect=postgresql.dialect()))
                return ResultStub()

        session = SessionStub()
        repository = ActivityRepository(session)
        result = asyncio.run(
            repository.get_summary_for_farm(
                uuid4(),
                datetime.now(UTC),
                datetime.now(UTC) - timedelta(days=7),
                datetime.now(UTC) - timedelta(days=14),
            )
        )

        self.assertEqual(result["last_7_days_count"], 3)
        self.assertEqual(result["eggs"], 0)
        assert session.statement is not None
        self.assertIn("activities", session.statement)
        self.assertIn("last_7_days_count", session.statement)
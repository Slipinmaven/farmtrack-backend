import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.schemas.egg_loss import (
    EggLossBatchCreateRequest,
    EggLossCreateRequest,
)
from app.schemas.enums import ActivityEntityType, ActivityType, EggLossReason, ProductType
from app.services.egg_loss_service import EggLossService


class FakeUnitOfWork:
    def __init__(self):
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        self.commit_count += 1


class FakeProductRepository:
    def __init__(self, products):
        self.products = products
        self.locked_ids = []

    async def get_by_id_for_update(self, farm_id, product_id):
        self.locked_ids.append(product_id)
        product = self.products.get(product_id)
        if product is None or product.farm_id != farm_id:
            return None
        return product


class FakeProductUnitRepository:
    def __init__(self, units):
        self.units = units

    async def get_by_product_and_unit(self, product_id, unit_id):
        return self.units.get((product_id, unit_id))

    async def get_base_unit_for_product(self, product_id):
        return next(
            (
                product_unit.unit
                for (configured_product_id, _), product_unit in self.units.items()
                if configured_product_id == product_id
                and getattr(product_unit, "is_base_unit", False)
            ),
            None,
        )


class FakeEggCollectionRepository:
    def __init__(self, totals):
        self.totals = totals

    async def get_total_base_quantity(self, farm_id, product_id):
        return self.totals.get((farm_id, product_id), Decimal("0.000"))


class FakeEggLossRepository:
    def __init__(self, totals):
        self.totals = totals
        self.created = []

    async def get_total_base_quantity(self, farm_id, product_id):
        return self.totals.get((farm_id, product_id), Decimal("0.000"))

    async def create(self, farm_id, data):
        loss = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **data,
        )
        self.created.append(loss)
        self.totals[(farm_id, data["product_id"])] = (
            self.totals.get((farm_id, data["product_id"]), Decimal("0.000"))
            + loss.quantity * loss.conversion_factor
        )
        return loss

    async def list_by_farm(self, farm_id, **filters):
        return [loss for loss in self.created if loss.farm_id == farm_id]


class FakeSoldQuantityRepository:
    def __init__(self, totals=None):
        self.totals = totals or {}

    async def get_sold_base_quantity(self, farm_id, product_id):
        return self.totals.get((farm_id, product_id), Decimal("0.000"))


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class EggLossServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.farm = SimpleNamespace(id=self.farm_id, owner_id=uuid4())
        self.product_id = uuid4()
        self.dozen_unit_id = uuid4()
        self.piece_unit_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            farm_id=self.farm_id,
            name="Table eggs",
            product_type=ProductType.EGGS,
            is_active=True,
        )
        self.product_unit = SimpleNamespace(
            product_id=self.product_id,
            unit_id=self.dozen_unit_id,
            conversion_factor=Decimal("12.000"),
            unit=SimpleNamespace(name="dozen", abbreviation="doz"),
        )
        self.piece_unit = SimpleNamespace(
            product_id=self.product_id,
            unit_id=self.piece_unit_id,
            conversion_factor=Decimal("1.000"),
            unit=SimpleNamespace(name="piece", abbreviation="pc"),
            is_base_unit=True,
        )
        self.product_repository = FakeProductRepository({self.product_id: self.product})
        self.collection_repository = FakeEggCollectionRepository(
            {(self.farm_id, self.product_id): Decimal("60.000")}
        )
        self.loss_repository = FakeEggLossRepository(
            {(self.farm_id, self.product_id): Decimal("18.000")}
        )
        self.activity_service = FakeActivityService()
        self.unit_of_work = FakeUnitOfWork()
        self.sold_quantity_repository = FakeSoldQuantityRepository()
        self.service = EggLossService(
            loss_repository=cast(Any, self.loss_repository),
            collection_repository=cast(Any, self.collection_repository),
            product_repository=cast(Any, self.product_repository),
            product_unit_repository=cast(
                Any,
                FakeProductUnitRepository(
                    {
                        (self.product_id, self.dozen_unit_id): self.product_unit,
                        (self.product_id, self.piece_unit_id): self.piece_unit,
                    }
                ),
            ),
            transaction_item_repository=cast(
                Any,
                self.sold_quantity_repository,
            ),
            unit_of_work=cast(Any, self.unit_of_work),
            activity_service=cast(Any, self.activity_service),
        )

    def _batch_request(self, items):
        return cast(Any, EggLossBatchCreateRequest).model_validate(
            {
                "product_id": str(self.product_id),
                "loss_date": date(2026, 10, 10),
                "reason": EggLossReason.BROKEN.value,
                "items": items,
                "notes": "Mixed-unit loss",
            }
        )

    def _request(self, **overrides):
        data = {
            "product_id": str(self.product_id),
            "quantity": "2",
            "unit_id": str(self.dozen_unit_id),
            "loss_date": date(2026, 10, 10),
            "reason": EggLossReason.BROKEN.value,
            "notes": "Broken during sorting",
        }
        data.update(overrides)
        return cast(Any, EggLossCreateRequest).model_validate(data)

    async def test_loss_decreases_derived_stock_and_records_activity(self):
        response = await self.service.create_loss(self.farm, self._request())

        self.assertEqual(response.quantity_in_base_unit, Decimal("24.000"))
        self.assertEqual(self.collection_repository.totals[(self.farm_id, self.product_id)], Decimal("60.000"))
        self.assertEqual(self.loss_repository.totals[(self.farm_id, self.product_id)], Decimal("42.000"))
        self.assertEqual(self.product_repository.locked_ids, [self.product_id])
        event = self.activity_service.events[0]
        self.assertEqual(event["activity_type"], ActivityType.EGG_LOSS_RECORDED)
        self.assertEqual(event["entity_type"], ActivityEntityType.EGG_LOSS)
        self.assertEqual(event["details"]["remaining_inventory_in_base_unit"], "18.000")
        self.assertEqual(event["details"]["base_unit_name"], "piece")
        self.assertEqual(
            event["details"]["items"][0]["unit_abbreviation"],
            "doz",
        )

    async def test_cannot_write_off_more_than_available_collected_eggs(self):
        with self.assertRaises(ConflictError):
            await self.service.create_loss(
                self.farm,
                self._request(quantity="4"),
            )

        self.assertEqual(self.loss_repository.created, [])
        self.assertEqual(self.activity_service.events, [])

    async def test_cannot_write_off_eggs_that_have_already_been_sold(self):
        self.sold_quantity_repository.totals[(self.farm_id, self.product_id)] = (
            Decimal("30.000")
        )

        with self.assertRaises(ConflictError):
            await self.service.create_loss(self.farm, self._request(quantity="2"))

        self.assertEqual(self.loss_repository.created, [])
        self.assertEqual(self.activity_service.events, [])

    async def test_mixed_unit_loss_is_created_as_one_atomic_batch(self):
        results = await self.service.create_batch_loss(
            self.farm,
            self._batch_request(
                [
                    {"quantity": "2", "unit_id": str(self.dozen_unit_id)},
                    {"quantity": "5", "unit_id": str(self.piece_unit_id)},
                ]
            ),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [result.quantity_in_base_unit for result in results],
            [Decimal("24.000"), Decimal("5.000")],
        )
        self.assertEqual(
            self.loss_repository.totals[(self.farm_id, self.product_id)],
            Decimal("47.000"),
        )
        self.assertEqual(self.unit_of_work.commit_count, 1)
        self.assertEqual(len(self.activity_service.events), 1)
        self.assertEqual(
            self.activity_service.events[0]["details"]["quantity_in_base_unit"],
            "29.000",
        )

    async def test_mixed_unit_batch_over_available_stock_writes_nothing(self):
        with self.assertRaises(ConflictError):
            await self.service.create_batch_loss(
                self.farm,
                self._batch_request(
                    [
                        {"quantity": "4", "unit_id": str(self.dozen_unit_id)},
                        {"quantity": "1", "unit_id": str(self.piece_unit_id)},
                    ]
                ),
            )

        self.assertEqual(self.loss_repository.created, [])
        self.assertEqual(self.activity_service.events, [])
        self.assertEqual(self.unit_of_work.commit_count, 0)

    async def test_rejects_wrong_product_type_and_unconfigured_unit(self):
        self.product.product_type = ProductType.CHICKENS
        with self.assertRaises(ConflictError):
            await self.service.create_loss(self.farm, self._request())

        self.product.product_type = ProductType.EGGS
        with self.assertRaises(ConflictError):
            await self.service.create_loss(
                self.farm,
                self._request(unit_id=str(uuid4())),
            )

        self.assertEqual(self.loss_repository.created, [])

    async def test_rejects_inactive_egg_product(self):
        self.product.is_active = False

        with self.assertRaises(ConflictError):
            await self.service.create_loss(self.farm, self._request())

        self.assertEqual(self.loss_repository.created, [])
        self.assertEqual(self.activity_service.events, [])

    async def test_rejects_product_outside_farm(self):
        self.product.farm_id = uuid4()

        with self.assertRaises(ResourceNotFoundError):
            await self.service.create_loss(self.farm, self._request())

        self.assertEqual(self.loss_repository.created, [])

    async def test_request_rejects_nonpositive_quantity(self):
        with self.assertRaises(ValidationError):
            self._request(quantity="0")


if __name__ == "__main__":
    unittest.main()

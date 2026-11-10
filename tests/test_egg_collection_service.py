import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.schemas.egg_collection import EggCollectionCreateRequest
from app.schemas.enums import ActivityEntityType, ActivityType, ProductType
from app.services.egg_collection_service import EggCollectionService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        pass


class FakeProductRepository:
    def __init__(self, products):
        self.products = products

    async def get_by_id(self, farm_id, product_id):
        product = self.products.get(product_id)
        if product is None or product.farm_id != farm_id:
            return None
        return product

    async def get_by_id_for_update(self, farm_id, product_id):
        return await self.get_by_id(farm_id, product_id)


class FakeProductUnitRepository:
    def __init__(self, product_units):
        self.product_units = product_units

    async def get_by_product_and_unit(self, product_id, unit_id):
        return self.product_units.get((product_id, unit_id))

    async def get_base_unit_for_product(self, product_id):
        return next(
            (
                product_unit.unit
                for (configured_product_id, _), product_unit in self.product_units.items()
                if configured_product_id == product_id
                and getattr(product_unit, "is_base_unit", False)
            ),
            None,
        )


class FakeBlockRepository:
    def __init__(self, blocks):
        self.blocks = blocks

    async def get_by_id(self, farm_id, block_id):
        block = self.blocks.get(block_id)
        if block is None or block.farm_id != farm_id:
            return None
        return block


class FakeCollectionRepository:
    def __init__(self):
        self.collections = []

    async def create_many(self, farm_id, records):
        created = [
            SimpleNamespace(
                id=uuid4(),
                farm_id=farm_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                **data,
            )
            for data in records
        ]
        self.collections.extend(created)
        return created

    async def list_by_farm(self, farm_id, **filters):
        return [record for record in self.collections if record.farm_id == farm_id]


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class EggCollectionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.farm = SimpleNamespace(id=self.farm_id, owner_id=uuid4())
        self.product_id = uuid4()
        self.block_id = uuid4()
        self.tray_unit_id = uuid4()
        self.piece_unit_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            farm_id=self.farm_id,
            name="Table eggs",
            product_type=ProductType.EGGS,
            is_active=True,
        )
        self.block = SimpleNamespace(
            id=self.block_id,
            farm_id=self.farm_id,
            name="Layer house",
            is_active=True,
        )
        self.product_unit = SimpleNamespace(
            product_id=self.product_id,
            unit_id=self.tray_unit_id,
            conversion_factor=Decimal("30.000"),
            unit=SimpleNamespace(name="tray", abbreviation="tray"),
        )
        self.piece_product_unit = SimpleNamespace(
            product_id=self.product_id,
            unit_id=self.piece_unit_id,
            conversion_factor=Decimal("1.000"),
            unit=SimpleNamespace(name="piece", abbreviation="pc"),
            is_base_unit=True,
        )
        self.collection_repository = FakeCollectionRepository()
        self.activity_service = FakeActivityService()
        self.service = EggCollectionService(
            collection_repository=cast(Any, self.collection_repository),
            product_repository=cast(
                Any,
                FakeProductRepository({self.product_id: self.product}),
            ),
            product_unit_repository=cast(
                Any,
                FakeProductUnitRepository(
                    {
                        (self.product_id, self.tray_unit_id): self.product_unit,
                        (self.product_id, self.piece_unit_id): self.piece_product_unit,
                    }
                ),
            ),
            block_repository=cast(Any, FakeBlockRepository({self.block_id: self.block})),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
        )

    def _request(self, **overrides):
        data = {
            "collected_at": "2026-10-09T08:30:00+03:00",
            "items": [
                {
                    "product_id": str(self.product_id),
                    "block_id": str(self.block_id),
                    "quantity": "2.000",
                    "unit_id": str(self.tray_unit_id),
                    "notes": "Morning collection",
                }
            ],
        }
        if "quantity" in overrides or "unit_id" in overrides or "notes" in overrides:
            item = data["items"][0]
            for key in ("quantity", "unit_id", "notes"):
                if key in overrides:
                    item[key] = overrides.pop(key)
        data.update(overrides)
        return cast(Any, EggCollectionCreateRequest).model_validate(data)

    async def test_collection_uses_configured_conversion_and_records_activity(self):
        result = await self.service.create_collections(self.farm, self._request())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].quantity, Decimal("2.000"))
        self.assertEqual(result[0].conversion_factor, Decimal("30.000"))
        self.assertEqual(result[0].quantity_in_base_unit, Decimal("60.000"))
        self.assertEqual(len(self.collection_repository.collections), 1)
        event = self.activity_service.events[0]
        self.assertEqual(event["activity_type"], ActivityType.EGG_COLLECTION_RECORDED)
        self.assertEqual(event["entity_type"], ActivityEntityType.EGG_COLLECTION)
        self.assertEqual(
            event["details"]["quantity_in_base_unit_by_product"]["Table eggs"],
            "60.000",
        )
        self.assertEqual(
            event["details"]["base_unit_by_product"]["Table eggs"],
            "piece",
        )
        self.assertEqual(event["details"]["items"][0]["unit_abbreviation"], "tray")

    async def test_records_trays_and_pieces_in_one_atomic_collection(self):
        request = cast(Any, EggCollectionCreateRequest).model_validate(
            {
                "collected_at": "2026-10-09T08:30:00+03:00",
                "items": [
                    {
                        "product_id": str(self.product_id),
                        "block_id": str(self.block_id),
                        "quantity": "2",
                        "unit_id": str(self.tray_unit_id),
                        "notes": "Full trays",
                    },
                    {
                        "product_id": str(self.product_id),
                        "block_id": str(self.block_id),
                        "quantity": "3",
                        "unit_id": str(self.piece_unit_id),
                        "notes": "Loose eggs from partial tray",
                    },
                ],
            }
        )

        result = await self.service.create_collections(self.farm, request)

        self.assertEqual(len(result), 2)
        self.assertEqual(
            [item.quantity_in_base_unit for item in result],
            [Decimal("60.000"), Decimal("3.000")],
        )
        self.assertEqual(len(self.collection_repository.collections), 2)
        self.assertEqual(len(self.activity_service.events), 1)
        self.assertEqual(
            self.activity_service.events[0]["details"][
                "quantity_in_base_unit_by_product"
            ]["Table eggs"],
            "63.000",
        )

    async def test_combines_collection_entries_from_multiple_blocks(self):
        second_block_id = uuid4()
        self.service.block_repository.blocks[second_block_id] = SimpleNamespace(
            id=second_block_id,
            farm_id=self.farm_id,
            name="Rear house",
            is_active=True,
        )
        request = cast(Any, EggCollectionCreateRequest).model_validate(
            {
                "collected_at": "2026-10-09T08:30:00+03:00",
                "items": [
                    {
                        "product_id": str(self.product_id),
                        "block_id": str(self.block_id),
                        "quantity": "2",
                        "unit_id": str(self.tray_unit_id),
                    },
                    {
                        "product_id": str(self.product_id),
                        "block_id": str(second_block_id),
                        "quantity": "5",
                        "unit_id": str(self.piece_unit_id),
                    },
                ],
            }
        )

        result = await self.service.create_collections(self.farm, request)

        self.assertEqual(len(result), 2)
        self.assertEqual(
            [item.quantity_in_base_unit for item in result],
            [Decimal("60.000"), Decimal("5.000")],
        )
        self.assertEqual(len(self.activity_service.events), 1)
        self.assertEqual(
            self.activity_service.events[0]["details"][
                "quantity_in_base_unit_by_product"
            ]["Table eggs"],
            "65.000",
        )

    async def test_legacy_single_entry_payload_is_still_accepted(self):
        request = cast(Any, EggCollectionCreateRequest).model_validate(
            {
                "product_id": str(self.product_id),
                "block_id": str(self.block_id),
                "quantity": "1",
                "unit_id": str(self.piece_unit_id),
                "collected_at": "2026-10-09T08:30:00+03:00",
            }
        )

        result = await self.service.create_collections(self.farm, request)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].quantity_in_base_unit, Decimal("1.000"))

    async def test_invalid_entry_rejects_entire_batch_before_persistence(self):
        request = cast(Any, EggCollectionCreateRequest).model_validate(
            {
                "collected_at": "2026-10-09T08:30:00+03:00",
                "items": [
                    {
                        "product_id": str(self.product_id),
                        "block_id": str(self.block_id),
                        "quantity": "2",
                        "unit_id": str(self.tray_unit_id),
                    },
                    {
                        "product_id": str(self.product_id),
                        "block_id": str(self.block_id),
                        "quantity": "3",
                        "unit_id": str(uuid4()),
                    },
                ],
            }
        )

        with self.assertRaises(ConflictError):
            await self.service.create_collections(self.farm, request)

        self.assertEqual(self.collection_repository.collections, [])
        self.assertEqual(self.activity_service.events, [])

    async def test_rejects_non_egg_product(self):
        self.product.product_type = ProductType.CHICKENS

        with self.assertRaises(ConflictError):
            await self.service.create_collections(self.farm, self._request())

        self.assertEqual(self.collection_repository.collections, [])
        self.assertEqual(self.activity_service.events, [])

    async def test_rejects_unit_not_configured_for_egg_product(self):
        with self.assertRaises(ConflictError):
            await self.service.create_collections(
                self.farm,
                self._request(unit_id=str(uuid4())),
            )

        self.assertEqual(self.collection_repository.collections, [])

    async def test_rejects_inactive_or_foreign_block(self):
        self.block.is_active = False
        with self.assertRaises(ConflictError):
            await self.service.create_collections(self.farm, self._request())

        self.block.is_active = True
        self.block.farm_id = uuid4()
        with self.assertRaises(ResourceNotFoundError):
            await self.service.create_collections(self.farm, self._request())

    async def test_request_requires_positive_quantity_and_timezone(self):
        with self.assertRaises(ValidationError):
            self._request(quantity="0")

        with self.assertRaises(ValidationError):
            self._request(collected_at="2026-10-09T08:30:00")


if __name__ == "__main__":
    unittest.main()

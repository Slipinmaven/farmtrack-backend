import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import (
    ChickenBatchStatus,
    ChickenType,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.sale_delivery import SaleDeliveryCreateRequest
from app.services.sale_delivery_service import SaleDeliveryService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def flush(self):
        pass

    async def commit(self):
        pass


class FakeTransactionRepository:
    def __init__(self, transaction):
        self.transaction = transaction

    async def get_by_id_for_update(self, farm_id, transaction_id):
        if self.transaction.id == transaction_id:
            return self.transaction
        return None

    async def get_by_id(self, farm_id, transaction_id):
        if self.transaction.id == transaction_id:
            return self.transaction
        return None


class FakeProductRepository:
    def __init__(self, products):
        self.products = products

    async def get_by_id(self, farm_id, product_id):
        return self.products.get(product_id)


class FakeBatchBlockRepository:
    def __init__(self, assignments):
        self.assignments = assignments

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.assignments.get((batch_id, block_id))

    async def update(self, batch_block):
        return batch_block


class FakeBlockRepository:
    def __init__(self, blocks):
        self.blocks = blocks

    async def get_by_id_for_update(self, farm_id, block_id):
        return self.blocks.get(block_id)


class FakeChickenBatchRepository:
    def __init__(self, batches):
        self.batches = batches

    async def get_by_id(self, farm_id, batch_id):
        return self.batches.get(batch_id)


class FakeSaleDeliveryRepository:
    def __init__(self):
        self.deliveries = []
        self.items = []
        self.allocations = []

    async def get_delivered_quantities_by_transaction(self, transaction_id):
        quantities = {}
        for delivery in self.deliveries:
            if delivery.transaction_id != transaction_id:
                continue
            for item in delivery.items:
                quantities[item.transaction_item_id] = (
                    quantities.get(item.transaction_item_id, Decimal("0"))
                    + item.quantity
                )
        return quantities

    async def create_delivery(self, data):
        delivery = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            items=[],
            **data,
        )
        self.deliveries.append(delivery)
        return delivery

    async def create_item(self, data):
        item = SimpleNamespace(id=uuid4(), batch_allocations=[], **data)
        delivery = next(
            record
            for record in self.deliveries
            if record.id == data["sale_delivery_id"]
        )
        delivery.items.append(item)
        self.items.append(item)
        return item

    async def create_allocation(self, data):
        allocation = SimpleNamespace(**data)
        self.allocations.append(allocation)
        item = next(
            record
            for record in self.items
            if record.id == data["sale_delivery_item_id"]
        )
        item.batch_allocations.append(allocation)

    async def list_by_transaction(self, transaction_id):
        return [
            delivery
            for delivery in self.deliveries
            if delivery.transaction_id == transaction_id
        ]


class FakeSaleReturnRepository:
    def __init__(self):
        self.cancelled = {}

    async def get_quantities_by_type(self, transaction_id, return_type):
        if return_type == "undelivered_cancelled":
            return self.cancelled
        return {}


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **kwargs):
        self.events.append(kwargs)


class SaleDeliveryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.transaction_id = uuid4()
        self.product_id = uuid4()
        self.batch_id = uuid4()
        self.block_id = uuid4()
        self.transaction_item_id = uuid4()

        batch = SimpleNamespace(
            id=self.batch_id,
            farm_id=self.farm_id,
            name="Layer flock",
            status=ChickenBatchStatus.ACTIVE,
            chicken_type=ChickenType.LAYERS,
        )
        block = SimpleNamespace(
            id=self.block_id,
            farm_id=self.farm_id,
            name="East house",
            is_active=True,
        )
        product = SimpleNamespace(
            id=self.product_id,
            farm_id=self.farm_id,
            name="Layer chickens",
            product_type=ProductType.CHICKENS,
            is_active=True,
        )
        transaction = SimpleNamespace(
            id=self.transaction_id,
            farm_id=self.farm_id,
            contact_id=None,
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            reference_number="SAL-TEST-0001",
            items=[
                SimpleNamespace(
                    id=self.transaction_item_id,
                    product_id=self.product_id,
                    quantity=Decimal("10"),
                    conversion_factor=Decimal("1"),
                    chicken_type=ChickenType.LAYERS,
                )
            ],
        )
        self.batch_block = SimpleNamespace(
            batch_id=self.batch_id,
            block_id=self.block_id,
            quantity=3,
        )
        batch_repository = FakeChickenBatchRepository({self.batch_id: batch})
        block_repository = FakeBlockRepository({self.block_id: block})
        batch_block_repository = FakeBatchBlockRepository(
            {(self.batch_id, self.block_id): self.batch_block}
        )
        self.delivery_repository = FakeSaleDeliveryRepository()
        self.sale_return_repository = FakeSaleReturnRepository()
        self.activity_service = FakeActivityService()
        self.service = SaleDeliveryService(
            transaction_repository=FakeTransactionRepository(transaction),
            product_repository=FakeProductRepository({self.product_id: product}),
            batch_repository=batch_repository,
            block_repository=block_repository,
            batch_block_repository=batch_block_repository,
            sale_delivery_repository=cast(Any, self.delivery_repository),
            sale_return_repository=cast(Any, self.sale_return_repository),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
        )
        self.batch_repository = batch_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository

    def _request(self, quantity):
        return cast(Any, SaleDeliveryCreateRequest).model_validate(
            {
                "delivered_date": date(2026, 10, 9),
                "items": [
                    {
                        "transaction_item_id": str(self.transaction_item_id),
                        "quantity_delivered": quantity,
                        "batch_allocations": [
                            {
                                "batch_id": str(self.batch_id),
                                "block_id": str(self.block_id),
                                "quantity": quantity,
                            }
                        ],
                    }
                ],
            }
        )

    async def test_delivery_cannot_exceed_available_batch_stock(self):
        with self.assertRaises(ConflictError):
            await self.service.create_delivery(
                self.farm_id,
                self.transaction_id,
                self._request(4),
            )
        self.assertEqual(self.batch_block.quantity, 3)
        self.assertEqual(self.delivery_repository.deliveries, [])

    async def test_partial_delivery_can_be_completed_after_restock(self):
        first_delivery = await self.service.create_delivery(
            self.farm_id,
            self.transaction_id,
            self._request(3),
        )
        self.assertEqual(first_delivery.items[0].remaining_quantity, Decimal("7"))
        self.assertEqual(self.batch_block.quantity, 0)

        self.batch_block.quantity = 7
        second_delivery = await self.service.create_delivery(
            self.farm_id,
            self.transaction_id,
            self._request(7),
        )
        self.assertEqual(second_delivery.items[0].remaining_quantity, Decimal("0"))
        self.assertEqual(self.batch_block.quantity, 0)
        activity_item = self.activity_service.events[-1]["details"]["items"][0]
        self.assertEqual(activity_item["product_name"], "Layer chickens")
        self.assertEqual(
            activity_item["allocations"][0]["batch_name"],
            "Layer flock",
        )
        self.assertEqual(
            activity_item["allocations"][0]["block_name"],
            "East house",
        )

        fulfillment = await self.service.get_fulfillment(
            self.farm_id,
            self.transaction_id,
        )
        self.assertTrue(fulfillment.fully_delivered)
        self.assertEqual(fulfillment.items[0].delivered_quantity, Decimal("10"))
        self.assertEqual(fulfillment.items[0].outstanding_quantity, Decimal("0"))

    async def test_rejects_delivery_beyond_cumulative_order_quantity(self):
        self.batch_block.quantity = 10
        await self.service.create_delivery(
            self.farm_id,
            self.transaction_id,
            self._request(6),
        )
        with self.assertRaises(ConflictError):
            await self.service.create_delivery(
                self.farm_id,
                self.transaction_id,
                self._request(5),
            )
        self.assertEqual(self.batch_block.quantity, 4)
        self.assertEqual(len(self.delivery_repository.deliveries), 1)

    async def test_cannot_deliver_quantity_already_cancelled(self):
        self.sale_return_repository.cancelled[self.transaction_item_id] = Decimal("8")

        with self.assertRaises(ConflictError):
            await self.service.create_delivery(
                self.farm_id,
                self.transaction_id,
                self._request(3),
            )

        self.assertEqual(self.batch_block.quantity, 3)
        self.assertEqual(self.delivery_repository.deliveries, [])

    async def test_delivery_can_span_batches_and_blocks(self):
        second_batch_id = uuid4()
        second_block_id = uuid4()
        self.batch_repository.batches[second_batch_id] = SimpleNamespace(
            id=second_batch_id,
            farm_id=self.farm_id,
            name="Broiler flock",
            status=ChickenBatchStatus.ACTIVE,
            chicken_type=ChickenType.LAYERS,
        )
        self.block_repository.blocks[second_block_id] = SimpleNamespace(
            id=second_block_id,
            farm_id=self.farm_id,
            name="West house",
            is_active=True,
        )
        second_block_same_batch = SimpleNamespace(
            batch_id=self.batch_id,
            block_id=second_block_id,
            quantity=3,
        )
        second_batch_same_block = SimpleNamespace(
            batch_id=second_batch_id,
            block_id=self.block_id,
            quantity=4,
        )
        self.batch_block_repository.assignments.update(
            {
                (self.batch_id, second_block_id): second_block_same_batch,
                (second_batch_id, self.block_id): second_batch_same_block,
            }
        )
        request = cast(Any, SaleDeliveryCreateRequest).model_validate(
            {
                "delivered_date": date(2026, 10, 9),
                "items": [
                    {
                        "transaction_item_id": str(self.transaction_item_id),
                        "quantity_delivered": 5,
                        "batch_allocations": [
                            {
                                "batch_id": str(self.batch_id),
                                "block_id": str(self.block_id),
                                "quantity": 2,
                            },
                            {
                                "batch_id": str(self.batch_id),
                                "block_id": str(second_block_id),
                                "quantity": 1,
                            },
                            {
                                "batch_id": str(second_batch_id),
                                "block_id": str(self.block_id),
                                "quantity": 2,
                            },
                        ],
                    }
                ],
            }
        )

        delivery = await self.service.create_delivery(
            self.farm_id,
            self.transaction_id,
            request,
        )

        self.assertEqual(len(delivery.items[0].batch_allocations), 3)
        self.assertEqual(self.batch_block.quantity, 1)
        self.assertEqual(second_block_same_batch.quantity, 2)
        self.assertEqual(second_batch_same_block.quantity, 2)


if __name__ == "__main__":
    unittest.main()

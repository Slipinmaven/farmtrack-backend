import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.dialects import postgresql

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.schemas.chicken_purchase import PurchaseReceiptCreateRequest
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    AgeUnit,
    ChickenBatchStatus,
    ChickenType,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.services.purchase_receipt_service import (
    PurchaseReceiptService,
    _calculate_hatch_date,
)
from app.repositories.transaction_repository import TransactionRepository


class FakeUnitOfWork:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            self.rollbacks += 1
        return False

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class FakeTransactionRepository:
    def __init__(self, transaction):
        self.transaction = transaction

    async def get_by_id_for_update(self, farm_id, transaction_id):
        if transaction_id != self.transaction.id:
            return None
        return self.transaction


class FakeProductRepository:
    def __init__(self, product):
        self.product = product

    async def get_by_id(self, farm_id, product_id):
        if product_id != self.product.id:
            return None
        return self.product


class FakeReceiptRepository:
    def __init__(self):
        self.receipts = {}

    async def create(self, receipt_data):
        receipt = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            **receipt_data,
        )
        self.receipts[receipt.id] = receipt
        return receipt


class FakeReceiptItemRepository:
    def __init__(self, receipt_repository):
        self.receipt_repository = receipt_repository
        self.received = {}

    async def get_received_quantities_by_transaction(self, transaction_id):
        return {
            item_id: quantity
            for (receipt_transaction_id, item_id), quantity in self.received.items()
            if receipt_transaction_id == transaction_id
        }

    async def create(self, item_data):
        receipt = self.receipt_repository.receipts[item_data["purchase_receipt_id"]]
        key = (receipt.transaction_id, item_data["transaction_item_id"])
        self.received[key] = self.received.get(key, Decimal("0")) + item_data["quantity"]
        return SimpleNamespace(id=uuid4(), **item_data)


class FakeChickenBatchRepository:
    def __init__(self, batch):
        self.batches = {batch.id: batch} if batch is not None else {}
        self.created_data = []

    async def get_by_id(self, farm_id, batch_id):
        return self.batches.get(batch_id)

    async def create(self, farm_id, batch_data):
        batch = SimpleNamespace(id=uuid4(), farm_id=farm_id, **batch_data)
        self.batches[batch.id] = batch
        self.created_data.append(batch_data)
        return batch


class FakeChickenBatchNameCounterRepository:
    def __init__(self):
        self.counters = {}

    async def allocate_next_number(self, farm_id, batch_date):
        key = (farm_id, batch_date)
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


class FakeChickenTransactionItemRepository:
    def __init__(self):
        self.items = {}

    async def get_by_transaction_item(self, transaction_item_id):
        return self.items.get(transaction_item_id)

    async def create(self, item_data):
        item = SimpleNamespace(id=uuid4(), **item_data)
        self.items[item.transaction_item_id] = item
        return item


class FakeReceiptBlockAllocationRepository:
    def __init__(self):
        self.allocations = []
        self.fail = False

    async def create(self, allocation_data):
        if self.fail:
            raise RuntimeError("allocation write failed")
        allocation = SimpleNamespace(id=uuid4(), **allocation_data)
        self.allocations.append(allocation)
        return allocation


class FakeBlockRepository:
    def __init__(self, blocks):
        self.blocks = {block.id: block for block in blocks}

    async def get_by_id_for_update(self, farm_id, block_id):
        return self.blocks.get(block_id)


class FakeBatchBlockRepository:
    def __init__(self):
        self.assignments = {}

    async def get_total_quantity_by_block(self, block_id):
        return sum(
            assignment.quantity
            for (_, assignment_block_id), assignment in self.assignments.items()
            if assignment_block_id == block_id
        )

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.assignments.get((batch_id, block_id))

    async def create(self, assignment_data):
        assignment = SimpleNamespace(**assignment_data)
        self.assignments[(assignment.batch_id, assignment.block_id)] = assignment
        return assignment

    async def update(self, assignment):
        return assignment


class PurchaseReceiptServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_purchase_lookup_uses_row_lock_for_concurrent_receipts(self):
        class CapturingSession:
            async def execute(self, statement):
                self.statement = statement
                return SimpleNamespace(scalar_one_or_none=lambda: None)

        session = CapturingSession()
        repository_factory: Any = TransactionRepository
        repository = repository_factory(session)

        await repository.get_by_id_for_update(uuid4(), uuid4())

        sql = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE OF transactions", sql)

    def _build_context(
        self,
        *,
        ordered_quantity=100,
        transaction_status=TransactionStatus.COMPLETED,
        block_capacities=(1000,),
        existing_batch=True,
        item_chicken_type: ChickenType | None = ChickenType.LAYERS,
    ):
        farm_id = uuid4()
        transaction_id = uuid4()
        transaction_item_id = uuid4()
        product_id = uuid4()
        batch_id = uuid4()
        transaction = SimpleNamespace(
            id=transaction_id,
            transaction_type=TransactionType.PURCHASE,
            status=transaction_status,
            items=[
                SimpleNamespace(
                    id=transaction_item_id,
                    product_id=product_id,
                    chicken_type=item_chicken_type,
                    quantity=Decimal(ordered_quantity),
                    conversion_factor=Decimal("1"),
                )
            ],
        )
        product = SimpleNamespace(id=product_id, product_type=ProductType.CHICKENS)
        batch = (
            SimpleNamespace(
                id=batch_id,
                status=ChickenBatchStatus.ACTIVE,
                chicken_type=ChickenType.LAYERS,
                hatch_date=None,
            )
            if existing_batch
            else None
        )
        blocks = [
            SimpleNamespace(
                id=uuid4(),
                name=f"Block {index}",
                is_active=True,
                capacity=capacity,
                over_capacity_limit=0,
            )
            for index, capacity in enumerate(block_capacities, start=1)
        ]
        receipt_repository = FakeReceiptRepository()
        receipt_item_repository = FakeReceiptItemRepository(receipt_repository)
        receipt_allocation_repository = FakeReceiptBlockAllocationRepository()
        chicken_batch_repository = FakeChickenBatchRepository(batch)
        chicken_batch_name_counter_repository = (
            FakeChickenBatchNameCounterRepository()
        )
        chicken_item_repository = FakeChickenTransactionItemRepository()
        block_repository = FakeBlockRepository(blocks)
        batch_block_repository = FakeBatchBlockRepository()
        unit_of_work = FakeUnitOfWork()
        activity_service = FakeActivityService()
        service = PurchaseReceiptService(
            transaction_repository=cast(Any, FakeTransactionRepository(transaction)),
            product_repository=cast(Any, FakeProductRepository(product)),
            receipt_repository=cast(Any, receipt_repository),
            receipt_item_repository=cast(Any, receipt_item_repository),
            receipt_item_block_allocation_repository=cast(
                Any,
                receipt_allocation_repository,
            ),
            chicken_batch_repository=cast(Any, chicken_batch_repository),
            chicken_transaction_item_repository=cast(Any, chicken_item_repository),
            block_repository=cast(Any, block_repository),
            batch_block_repository=cast(Any, batch_block_repository),
            unit_of_work=cast(Any, unit_of_work),
            activity_service=cast(Any, activity_service),
            chicken_batch_name_counter_repository=cast(
                Any,
                chicken_batch_name_counter_repository,
            ),
        )
        return SimpleNamespace(
            service=service,
            farm_id=farm_id,
            transaction_id=transaction_id,
            transaction_item_id=transaction_item_id,
            batch_id=batch_id,
            blocks=blocks,
            receipts=receipt_repository,
            receipt_items=receipt_item_repository,
            receipt_allocations=receipt_allocation_repository,
            batches=chicken_batch_repository,
            batch_name_counters=chicken_batch_name_counter_repository,
            chicken_items=chicken_item_repository,
            batch_blocks=batch_block_repository,
            unit_of_work=unit_of_work,
            activity_service=activity_service,
        )

    async def _receive(
        self,
        context,
        quantity: int,
        assignment: Any,
        allocations: list[tuple[UUID, int]] | None = None,
        received_date: date | None = None,
    ):
        if allocations is None:
            allocations = [(context.blocks[0].id, quantity)]
        return await context.service.create_receipt(
            context.farm_id,
            PurchaseReceiptCreateRequest.model_validate(
                {
                    "transaction_id": context.transaction_id,
                    "received_date": received_date or date(2026, 10, 9),
                    "items": [
                        {
                            "transaction_item_id": context.transaction_item_id,
                            "quantity_received": quantity,
                            "batch_assignment": assignment,
                            "block_allocations": [
                                {"block_id": block_id, "quantity": allocation_quantity}
                                for block_id, allocation_quantity in allocations
                            ],
                        }
                    ],
                }
            ),
        )

    async def test_partial_receipts_accumulate_and_over_delivery_is_rejected(self):
        farm_id = uuid4()
        transaction_id = uuid4()
        transaction_item_id = uuid4()
        product_id = uuid4()
        unit_id = uuid4()
        batch_id = uuid4()
        block_id = uuid4()
        transaction = SimpleNamespace(
            id=transaction_id,
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            items=[
                SimpleNamespace(
                    id=transaction_item_id,
                    product_id=product_id,
                    chicken_type=ChickenType.LAYERS,
                    quantity=Decimal("400"),
                    conversion_factor=Decimal("1"),
                )
            ],
        )
        product = SimpleNamespace(id=product_id, product_type=ProductType.CHICKENS)
        batch = SimpleNamespace(
            id=batch_id,
            status=ChickenBatchStatus.ACTIVE,
            chicken_type=ChickenType.LAYERS,
            hatch_date=None,
        )
        block = SimpleNamespace(
            id=block_id,
            name="Brooder 1",
            is_active=True,
            capacity=400,
            over_capacity_limit=0,
        )
        receipt_repository = FakeReceiptRepository()
        receipt_item_repository = FakeReceiptItemRepository(receipt_repository)
        batch_block_repository = FakeBatchBlockRepository()
        unit_of_work = FakeUnitOfWork()
        activity_service = FakeActivityService()
        chicken_item_repository = FakeChickenTransactionItemRepository()
        service = PurchaseReceiptService(
            transaction_repository=cast(Any, FakeTransactionRepository(transaction)),
            product_repository=cast(Any, FakeProductRepository(product)),
            receipt_repository=cast(Any, receipt_repository),
            receipt_item_repository=cast(Any, receipt_item_repository),
            receipt_item_block_allocation_repository=cast(
                Any,
                FakeReceiptBlockAllocationRepository(),
            ),
            chicken_batch_repository=cast(Any, FakeChickenBatchRepository(batch)),
            chicken_transaction_item_repository=cast(Any, chicken_item_repository),
            block_repository=cast(Any, FakeBlockRepository([block])),
            batch_block_repository=cast(Any, batch_block_repository),
            unit_of_work=cast(Any, unit_of_work),
            activity_service=cast(Any, activity_service),
        )

        async def receive(quantity: int, batch_assignment: Any = None):
            if batch_assignment is None and transaction_item_id not in chicken_item_repository.items:
                batch_assignment = {
                    "action": "USE_EXISTING",
                    "batch_id": batch_id,
                }
            return await service.create_receipt(
                farm_id,
                PurchaseReceiptCreateRequest.model_validate(
                    {
                        "transaction_id": transaction_id,
                        "received_date": date(2026, 10, 9),
                        "items": [
                            {
                                "transaction_item_id": transaction_item_id,
                                "quantity_received": quantity,
                                "batch_assignment": batch_assignment,
                                "block_allocations": [
                                    {"block_id": block_id, "quantity": quantity}
                                ],
                            }
                        ],
                    }
                ),
            )

        first = await receive(250)
        second = await receive(100, batch_assignment=None)
        final = await receive(50, batch_assignment=None)

        self.assertEqual(
            [
                receipt.items[0].quantity_received
                for receipt in (first, second, final)
            ],
            [Decimal("250"), Decimal("100"), Decimal("50")],
        )
        self.assertEqual(first.items[0].remaining_quantity, Decimal("150"))
        self.assertEqual(second.items[0].remaining_quantity, Decimal("50"))
        self.assertEqual(final.items[0].remaining_quantity, Decimal("0"))
        self.assertEqual(first.items[0].batch_id, batch_id)
        self.assertEqual(
            batch_block_repository.assignments[(batch_id, block_id)].quantity,
            400,
        )
        with self.assertRaises(ConflictError):
            await receive(1, batch_assignment=None)
        self.assertEqual(len(receipt_repository.receipts), 3)
        self.assertEqual(unit_of_work.commits, 3)
        self.assertEqual(
            activity_service.events[-1]["activity_type"],
            ActivityType.PURCHASE_RECEIPT_CREATED,
        )
        self.assertEqual(
            activity_service.events[-1]["entity_type"],
            ActivityEntityType.PURCHASE_RECEIPT,
        )

    async def test_new_batch_calculates_hatch_date_and_links_purchase_item(self):
        context = self._build_context(existing_batch=False)
        response = await self._receive(
            context,
            25,
            {
                "action": "CREATE",
                "new_batch": {
                    "name": "October Layers",
                    "chicken_type": "layers",
                    "age": 2,
                    "age_unit": "weeks",
                },
            },
            received_date=date(2026, 10, 10),
        )

        batch = next(iter(context.batches.batches.values()))
        self.assertEqual(batch.hatch_date, date(2026, 9, 26))
        self.assertEqual(response.items[0].batch_id, batch.id)
        self.assertEqual(
            context.chicken_items.items[context.transaction_item_id].batch_id,
            batch.id,
        )

    async def test_new_batch_name_uses_receipt_date_and_counter(self):
        context = self._build_context(existing_batch=False)
        response = await self._receive(
            context,
            25,
            {
                "action": "CREATE",
                "new_batch": {
                    "chicken_type": "layers",
                    "age": 2,
                    "age_unit": "weeks",
                },
            },
            received_date=date(2026, 10, 3),
        )

        batch = next(iter(context.batches.batches.values()))
        self.assertEqual(batch.name, "2026 October 3 Batch 1")
        self.assertEqual(response.items[0].batch_name, batch.name)

    async def test_age_units_use_calendar_aware_hatch_dates(self):
        received = date(2026, 10, 10)
        self.assertEqual(
            _calculate_hatch_date(received, 14, AgeUnit.DAYS),
            date(2026, 9, 26),
        )
        self.assertEqual(
            _calculate_hatch_date(received, 2, AgeUnit.WEEKS),
            date(2026, 9, 26),
        )
        self.assertEqual(
            _calculate_hatch_date(date(2026, 3, 31), 1, AgeUnit.MONTHS),
            date(2026, 2, 28),
        )
        self.assertEqual(
            _calculate_hatch_date(date(2025, 2, 28), 1, AgeUnit.YEARS),
            date(2024, 2, 28),
        )
        self.assertIsNone(_calculate_hatch_date(received, None, None))

    async def test_unlinked_item_requires_batch_assignment(self):
        context = self._build_context(existing_batch=False)
        with self.assertRaises(ConflictError):
            await self._receive(context, 10, None)

    async def test_linked_item_rejects_conflicting_batch_assignment(self):
        context = self._build_context()
        await context.chicken_items.create(
            {
                "transaction_item_id": context.transaction_item_id,
                "batch_id": context.batch_id,
                "block_id": None,
            }
        )
        with self.assertRaises(ConflictError):
            await self._receive(
                context,
                10,
                {"action": "USE_EXISTING", "batch_id": uuid4()},
            )

    async def test_batch_chicken_type_must_match_order_snapshot(self):
        context = self._build_context()
        context.batches.batches[context.batch_id].chicken_type = ChickenType.BROILER
        with self.assertRaises(ConflictError):
            await self._receive(
                context,
                10,
                {"action": "USE_EXISTING", "batch_id": context.batch_id},
            )

    async def test_legacy_null_subtype_is_backfilled_from_explicit_batch(self):
        context = self._build_context(
            item_chicken_type=cast(ChickenType | None, None)
        )
        await self._receive(
            context,
            10,
            {"action": "USE_EXISTING", "batch_id": context.batch_id},
        )

        self.assertEqual(
            context.service.transaction_repository.transaction.items[0].chicken_type,
            ChickenType.LAYERS,
        )

    async def test_cancelled_purchase_cannot_be_received(self):
        context = self._build_context(
            transaction_status=TransactionStatus.CANCELLED
        )
        with self.assertRaises(ConflictError):
            await self._receive(
                context,
                10,
                {"action": "USE_EXISTING", "batch_id": context.batch_id},
            )
        self.assertEqual(context.receipts.receipts, {})

    async def test_transaction_item_from_another_purchase_is_rejected(self):
        context = self._build_context()
        request = PurchaseReceiptCreateRequest.model_validate(
            {
                "transaction_id": context.transaction_id,
                "received_date": date(2026, 10, 9),
                "items": [
                    {
                        "transaction_item_id": uuid4(),
                        "quantity_received": 1,
                        "batch_assignment": {
                            "action": "USE_EXISTING",
                            "batch_id": context.batch_id,
                        },
                        "block_allocations": [
                            {"block_id": context.blocks[0].id, "quantity": 1}
                        ],
                    }
                ],
            }
        )
        with self.assertRaises(ResourceNotFoundError):
            await context.service.create_receipt(context.farm_id, request)

    async def test_block_from_another_farm_is_rejected(self):
        context = self._build_context()
        with self.assertRaises(ResourceNotFoundError):
            await self._receive(
                context,
                10,
                {"action": "USE_EXISTING", "batch_id": context.batch_id},
                allocations=[(uuid4(), 10)],
            )

    async def test_multiple_block_allocations_increment_current_stock(self):
        context = self._build_context(block_capacities=(100, 100))
        await self._receive(
            context,
            20,
            {"action": "USE_EXISTING", "batch_id": context.batch_id},
            allocations=[
                (context.blocks[0].id, 12),
                (context.blocks[1].id, 8),
            ],
        )
        for block, expected in zip(context.blocks, (12, 8)):
            self.assertEqual(
                context.batch_blocks.assignments[(context.batch_id, block.id)].quantity,
                expected,
            )
        self.assertEqual(len(context.receipt_allocations.allocations), 2)

    async def test_block_capacity_failure_rolls_back_receipt(self):
        context = self._build_context(block_capacities=(9,))
        with self.assertRaises(ConflictError):
            await self._receive(
                context,
                10,
                {"action": "USE_EXISTING", "batch_id": context.batch_id},
            )
        self.assertEqual(context.receipts.receipts, {})
        self.assertEqual(context.unit_of_work.commits, 0)

    async def test_allocation_write_failure_rolls_back_unit_of_work(self):
        context = self._build_context()
        context.receipt_allocations.fail = True
        with self.assertRaises(RuntimeError):
            await self._receive(
                context,
                10,
                {"action": "USE_EXISTING", "batch_id": context.batch_id},
            )
        self.assertEqual(context.unit_of_work.commits, 0)
        self.assertEqual(context.unit_of_work.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
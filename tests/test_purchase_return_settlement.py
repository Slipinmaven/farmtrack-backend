import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    ChickenType,
    PaymentMethod,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.purchase_return import PurchaseReturnCreateRequest
from app.schemas.purchase_replacement import PurchaseReplacementCreateRequest
from app.schemas.purchase_supplier_refund import PurchaseSupplierRefundCreateRequest
from app.services.purchase_return_service import PurchaseReturnService
from app.services.purchase_replacement_service import PurchaseReplacementService
from app.services.purchase_supplier_refund_service import PurchaseSupplierRefundService


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
        return self.transaction if self.transaction.id == transaction_id else None

    async def get_by_id(self, farm_id, transaction_id):
        return self.transaction if self.transaction.id == transaction_id else None


class FakeProductRepository:
    def __init__(self, product):
        self.product = product

    async def get_by_id(self, farm_id, product_id):
        if self.product.id == product_id and self.product.farm_id == farm_id:
            return self.product
        return None


class FakeChickenTransactionItemRepository:
    def __init__(self, links):
        self.links = links

    async def get_by_transaction_item(self, transaction_item_id):
        return self.links.get(transaction_item_id)


class FakeReceiptItemRepository:
    def __init__(self, received):
        self.received = received

    async def get_received_quantities_by_transaction(self, transaction_id):
        return self.received


class FakePurchaseReturnRepository:
    def __init__(self):
        self.returns = []
        self.items = []
        self.allocations = []

    async def get_returned_quantities(self, transaction_id):
        result = {}
        for item in self.items:
            result[item.transaction_item_id] = (
                result.get(item.transaction_item_id, Decimal("0")) + item.quantity
            )
        return result

    async def get_credit_amounts_by_item(self, transaction_id):
        result = {}
        for item in self.items:
            result[item.transaction_item_id] = (
                result.get(item.transaction_item_id, Decimal("0.00"))
                + item.credit_amount
            )
        return result

    async def get_total_credit_by_transaction(self, transaction_id):
        return sum((item.credit_amount for item in self.items), Decimal("0.00"))

    async def create_return(self, data):
        record = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            items=[],
            **data,
        )
        self.returns.append(record)
        return record

    async def create_item(self, data):
        item = SimpleNamespace(id=uuid4(), block_allocations=[], **data)
        record = next(value for value in self.returns if value.id == data["purchase_return_id"])
        record.items.append(item)
        self.items.append(item)
        return item

    async def create_allocation(self, data):
        allocation = SimpleNamespace(id=uuid4(), **data)
        self.allocations.append(allocation)
        item = next(value for value in self.items if value.id == data["purchase_return_item_id"])
        item.block_allocations.append(allocation)
        return allocation

    async def list_by_transaction(self, transaction_id):
        return self.returns

    async def get_return_item(self, transaction_id, return_item_id):
        return next((item for item in self.items if item.id == return_item_id), None)


class FakeSupplierRefundRepository:
    def __init__(self):
        self.refunds = []

    async def get_total_by_transaction(self, transaction_id):
        return sum((record.amount for record in self.refunds), Decimal("0.00"))

    async def get_total_by_return_item(self, return_item_id):
        return sum(
            (record.amount for record in self.refunds if record.purchase_return_item_id == return_item_id),
            Decimal("0.00"),
        )

    async def create(self, data):
        record = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            refund_time=None,
            reference_number=None,
            notes=None,
            **data,
        )
        self.refunds.append(record)
        return record

    async def list_by_transaction(self, transaction_id):
        return self.refunds


class FakeReplacementRepository:
    def __init__(self):
        self.replacements = []
        self.items = []
        self.allocations = []

    async def get_credit_applied_by_return_item(self, return_item_id):
        return sum(
            (item.credit_applied_amount for item in self.items if item.purchase_return_item_id == return_item_id),
            Decimal("0.00"),
        )

    async def get_total_credit_applied_by_transaction(self, transaction_id):
        return sum((item.credit_applied_amount for item in self.items), Decimal("0.00"))

    async def list_by_transaction(self, transaction_id):
        return self.replacements

    async def create_replacement(self, data):
        record = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            items=[],
            **data,
        )
        self.replacements.append(record)
        return record

    async def create_item(self, data):
        item = SimpleNamespace(id=uuid4(), block_allocations=[], **data)
        record = next(value for value in self.replacements if value.id == data["purchase_replacement_id"])
        record.items.append(item)
        self.items.append(item)
        return item

    async def create_allocation(self, data):
        allocation = SimpleNamespace(id=uuid4(), **data)
        self.allocations.append(allocation)
        item = next(value for value in self.items if value.id == data["purchase_replacement_item_id"])
        item.block_allocations.append(allocation)
        return allocation


class FakePaymentRepository:
    def __init__(self, payments):
        self.payments = payments

    async def list_by_transaction(self, transaction_id):
        return self.payments


class FakeChickenBatchRepository:
    def __init__(self, batches):
        self.batches = batches

    async def get_by_id(self, farm_id, batch_id):
        batch = self.batches.get(batch_id)
        if batch is None or batch.farm_id != farm_id:
            return None
        return batch


class FakeBlockRepository:
    def __init__(self, blocks):
        self.blocks = blocks

    async def get_by_id_for_update(self, farm_id, block_id):
        block = self.blocks.get(block_id)
        if block is None or block.farm_id != farm_id:
            return None
        return block


class FakeBatchBlockRepository:
    def __init__(self, assignments):
        self.assignments = assignments

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.assignments.get((batch_id, block_id))

    async def get_total_quantity_by_block(self, block_id):
        return sum(
            row.quantity
            for (_, candidate_block_id), row in self.assignments.items()
            if candidate_block_id == block_id
        )

    async def update(self, assignment):
        return assignment

    async def create(self, data):
        assignment = SimpleNamespace(**data)
        self.assignments[(data["batch_id"], data["block_id"])] = assignment
        return assignment


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class FakeInventoryService:
    def __init__(self):
        self.movements = []

    async def append_movement(self, **movement):
        self.movements.append(movement)


class PurchaseReturnSettlementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.transaction_id = uuid4()
        self.product_id = uuid4()
        self.layers_item_id = uuid4()
        self.broiler_item_id = uuid4()
        self.layers_batch_id = uuid4()
        self.broiler_batch_id = uuid4()
        self.blocks = [
            SimpleNamespace(
                id=uuid4(), farm_id=self.farm_id, name=f"Block {index}",
                is_active=True, capacity=300, over_capacity_limit=0,
            )
            for index in range(1, 6)
        ]
        self.layers_batch = SimpleNamespace(
            id=self.layers_batch_id, farm_id=self.farm_id,
            product_id=self.product_id,
            status=ChickenBatchStatus.ACTIVE, chicken_type=ChickenType.LAYERS,
            name="Layers",
        )
        self.broiler_batch = SimpleNamespace(
            id=self.broiler_batch_id, farm_id=self.farm_id,
            product_id=self.product_id,
            status=ChickenBatchStatus.ACTIVE, chicken_type=ChickenType.BROILER,
            name="Broilers",
        )
        self.layers_item = SimpleNamespace(
            id=self.layers_item_id, product_id=self.product_id,
            quantity=Decimal("300"), conversion_factor=Decimal("1"),
            total_amount=Decimal("30000.00"),
        )
        self.broiler_item = SimpleNamespace(
            id=self.broiler_item_id, product_id=self.product_id,
            quantity=Decimal("200"), conversion_factor=Decimal("1"),
            total_amount=Decimal("10000.00"),
        )
        self.transaction = SimpleNamespace(
            id=self.transaction_id, farm_id=self.farm_id,
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            reference_number=None,
            contact_id=None,
            settlements=[],
            items=[self.layers_item, self.broiler_item],
        )
        product = SimpleNamespace(
            id=self.product_id, farm_id=self.farm_id,
            product_type=ProductType.CHICKENS,
        )
        self.return_repository = FakePurchaseReturnRepository()
        self.refund_repository = FakeSupplierRefundRepository()
        self.replacement_repository = FakeReplacementRepository()
        self.payment_repository = FakePaymentRepository(
            [SimpleNamespace(amount=Decimal("40000.00"))]
        )
        self.inventory = {}
        for batch_id, block_indices in (
            (self.layers_batch_id, (0, 1, 2)),
            (self.broiler_batch_id, (3, 4)),
        ):
            for block_index in block_indices:
                block = self.blocks[block_index]
                self.inventory[(batch_id, block.id)] = SimpleNamespace(
                    batch_id=batch_id, block_id=block.id, quantity=100,
                )
        self.batch_block_repository = FakeBatchBlockRepository(self.inventory)
        self.batch_repository = FakeChickenBatchRepository(
            {
                self.layers_batch_id: self.layers_batch,
                self.broiler_batch_id: self.broiler_batch,
            }
        )
        self.transaction_repository = FakeTransactionRepository(self.transaction)
        self.activity_service = FakeActivityService()
        self.inventory_service = FakeInventoryService()
        self.unit_of_work = FakeUnitOfWork()
        self.return_service = PurchaseReturnService(
            transaction_repository=self.transaction_repository,
            product_repository=FakeProductRepository(product),
            chicken_transaction_item_repository=FakeChickenTransactionItemRepository(
                {
                    self.layers_item_id: SimpleNamespace(
                        batch_id=self.layers_batch_id, batch=self.layers_batch,
                    ),
                    self.broiler_item_id: SimpleNamespace(
                        batch_id=self.broiler_batch_id, batch=self.broiler_batch,
                    ),
                }
            ),
            receipt_item_repository=FakeReceiptItemRepository(
                {
                    self.layers_item_id: Decimal("300"),
                    self.broiler_item_id: Decimal("200"),
                }
            ),
            purchase_return_repository=self.return_repository,
            supplier_refund_repository=self.refund_repository,
            replacement_repository=self.replacement_repository,
            payment_repository=self.payment_repository,
            block_repository=FakeBlockRepository({block.id: block for block in self.blocks}),
            batch_block_repository=self.batch_block_repository,
            unit_of_work=self.unit_of_work,
            activity_service=self.activity_service,
            inventory_service=self.inventory_service,
        )
        self.supplier_refund_service = PurchaseSupplierRefundService(
            transaction_repository=self.transaction_repository,
            payment_repository=self.payment_repository,
            purchase_return_repository=self.return_repository,
            supplier_refund_repository=self.refund_repository,
            replacement_repository=self.replacement_repository,
            unit_of_work=self.unit_of_work,
            activity_service=self.activity_service,
        )
        self.replacement_service = PurchaseReplacementService(
            transaction_repository=self.transaction_repository,
            chicken_batch_repository=self.batch_repository,
            block_repository=FakeBlockRepository({block.id: block for block in self.blocks}),
            batch_block_repository=self.batch_block_repository,
            purchase_return_repository=self.return_repository,
            purchase_supplier_refund_repository=self.refund_repository,
            purchase_replacement_repository=self.replacement_repository,
            transaction_payment_repository=self.payment_repository,
            unit_of_work=self.unit_of_work,
            activity_service=self.activity_service,
        )

    def _return_request(self, quantity, allocations):
        return cast(Any, PurchaseReturnCreateRequest).model_validate(
            {
                "return_date": date(2026, 10, 9),
                "reason": "Sick chickens",
                "items": [
                    {
                        "transaction_item_id": str(self.layers_item_id),
                        "quantity_returned": quantity,
                        "block_allocations": [
                            {
                                "block_id": str(block_id),
                                "quantity": block_quantity,
                            }
                            for block_id, block_quantity in allocations
                        ],
                    }
                ],
            }
        )

    async def _create_ten_layer_return(self):
        return await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            self._return_request(
                10,
                [(self.blocks[0].id, 6), (self.blocks[1].id, 4)],
            ),
        )

    async def test_returns_ten_layers_from_two_blocks_and_creates_supplier_credit(self):
        result = await self._create_ten_layer_return()

        self.assertEqual(result.credit_total, Decimal("1000.00"))
        self.assertEqual(result.return_credit_remaining, Decimal("1000.00"))
        self.assertEqual(result.items[0].chicken_type, ChickenType.LAYERS)
        self.assertEqual(self.inventory[(self.layers_batch_id, self.blocks[0].id)].quantity, 94)
        self.assertEqual(self.inventory[(self.layers_batch_id, self.blocks[1].id)].quantity, 96)
        self.assertEqual(self.inventory[(self.layers_batch_id, self.blocks[2].id)].quantity, 100)
        self.assertEqual(
            self.activity_service.events[-1]["activity_type"],
            ActivityType.PURCHASE_RETURN_CREATED,
        )
        self.assertEqual(
            self.inventory_service.movements[0]["quantity_delta"],
            Decimal("-10"),
        )

    async def test_purchase_return_credit_remaining_accounts_for_transaction_settlements(self):
        self.transaction.settlements.append(
            SimpleNamespace(
                direction="contact_to_farm",
                total_value=Decimal("600.00"),
            )
        )

        result = await self._create_ten_layer_return()

        self.assertEqual(result.credit_balance, Decimal("400.00"))
        self.assertEqual(result.return_credit_remaining, Decimal("400.00"))

    async def test_purchase_return_rejects_batch_linked_to_another_product(self):
        self.layers_batch.product_id = uuid4()

        with self.assertRaisesRegex(ConflictError, "not linked to the selected"):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                self._return_request(10, [(self.blocks[0].id, 10)]),
            )

        self.assertEqual(self.return_repository.returns, [])
        self.assertEqual(
            self.inventory[(self.layers_batch_id, self.blocks[0].id)].quantity,
            100,
        )
        self.assertEqual(self.inventory_service.movements, [])

    async def test_non_chicken_purchase_return_updates_shared_inventory(self):
        self.return_service.product_repository.product.product_type = ProductType.FEED
        request = cast(Any, PurchaseReturnCreateRequest).model_validate(
            {
                "return_date": date(2026, 10, 11),
                "reason": "Damaged feed",
                "items": [
                    {
                        "transaction_item_id": str(self.layers_item_id),
                        "quantity_returned": "2.5",
                    }
                ],
            }
        )

        result = await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            request,
        )

        self.assertEqual(result.credit_total, Decimal("250.00"))
        self.assertEqual(
            self.inventory_service.movements[0]["quantity_delta"],
            Decimal("-2.5"),
        )
        self.assertEqual(
            self.inventory_service.movements[0]["movement_type"].value,
            "supplier_return",
        )

    async def test_cannot_return_more_than_received_or_stocked(self):
        with self.assertRaises(ConflictError):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                self._return_request(301, [(self.blocks[0].id, 301)]),
            )
        self.assertEqual(self.return_repository.returns, [])
        self.assertEqual(self.inventory[(self.layers_batch_id, self.blocks[0].id)].quantity, 100)

    async def test_supplier_cash_refund_settles_credit_and_adjusts_net_purchase_balance(self):
        await self._create_ten_layer_return()
        request = cast(Any, PurchaseSupplierRefundCreateRequest).model_validate(
            {
                "purchase_return_item_id": str(self.return_repository.items[0].id),
                "amount": "1000.00",
                "refund_date": date(2026, 10, 9),
                "payment_method": PaymentMethod.MPESA.value,
                "reason": "Sick chicken refund",
            }
        )

        result = await self.supplier_refund_service.create_refund(
            self.farm_id,
            self.transaction_id,
            request,
        )

        self.assertEqual(result.refund.amount, Decimal("1000.00"))
        self.assertEqual(result.return_credit_remaining, Decimal("0.00"))
        self.assertEqual(result.adjusted_transaction_total, Decimal("39000.00"))
        self.assertEqual(result.amount_paid, Decimal("39000.00"))
        self.assertEqual(result.balance_due, Decimal("0.00"))
        self.assertEqual(result.credit_balance, Decimal("0.00"))
        self.assertEqual(
            self.activity_service.events[-1]["entity_type"],
            ActivityEntityType.PURCHASE_SUPPLIER_REFUND,
        )

    async def test_supplier_refund_cannot_exceed_return_credit(self):
        await self._create_ten_layer_return()
        request = cast(Any, PurchaseSupplierRefundCreateRequest).model_validate(
            {
                "purchase_return_item_id": str(self.return_repository.items[0].id),
                "amount": "1000.01",
                "refund_date": date(2026, 10, 9),
                "payment_method": PaymentMethod.CASH.value,
                "reason": "Too much",
            }
        )

        with self.assertRaises(ConflictError):
            await self.supplier_refund_service.create_refund(
                self.farm_id,
                self.transaction_id,
                request,
            )
        self.assertEqual(self.refund_repository.refunds, [])

    async def test_supplier_refund_cannot_reuse_credit_consumed_by_settlement(self):
        await self._create_ten_layer_return()
        self.transaction.settlements.append(
            SimpleNamespace(
                direction="contact_to_farm",
                total_value=Decimal("600.00"),
            )
        )
        request = cast(Any, PurchaseSupplierRefundCreateRequest).model_validate(
            {
                "purchase_return_item_id": str(self.return_repository.items[0].id),
                "amount": "401.00",
                "refund_date": date(2026, 10, 9),
                "payment_method": PaymentMethod.CASH.value,
                "reason": "Exceeds remaining transaction credit",
            }
        )

        with self.assertRaises(ConflictError):
            await self.supplier_refund_service.create_refund(
                self.farm_id,
                self.transaction_id,
                request,
            )

        self.assertEqual(self.refund_repository.refunds, [])

    async def test_replacement_can_be_other_type_and_include_bonus_chicken(self):
        await self._create_ten_layer_return()
        request = cast(Any, PurchaseReplacementCreateRequest).model_validate(
            {
                "purchase_return_id": str(self.return_repository.returns[0].id),
                "replacement_date": date(2026, 10, 10),
                "items": [
                    {
                        "purchase_return_item_id": str(self.return_repository.items[0].id),
                        "batch_id": str(self.broiler_batch_id),
                        "quantity_received": 11,
                        "bonus_quantity": 1,
                        "credit_applied_amount": "1000.00",
                        "block_allocations": [
                            {"block_id": str(self.blocks[3].id), "quantity": 6},
                            {"block_id": str(self.blocks[4].id), "quantity": 5},
                        ],
                    }
                ],
            }
        )

        result = await self.replacement_service.create_replacement(
            self.farm_id,
            self.transaction_id,
            request,
        )

        item = result.items[0]
        self.assertEqual(item.chicken_type, ChickenType.BROILER)
        self.assertEqual(item.replacement_quantity, Decimal("10"))
        self.assertEqual(item.bonus_quantity, Decimal("1"))
        self.assertEqual(result.credit_applied_total, Decimal("1000.00"))
        self.assertEqual(result.return_credit_remaining, Decimal("0.00"))
        self.assertEqual(self.inventory[(self.broiler_batch_id, self.blocks[3].id)].quantity, 106)
        self.assertEqual(self.inventory[(self.broiler_batch_id, self.blocks[4].id)].quantity, 105)

        self.replacement_repository.items[0].batch = self.broiler_batch
        history = await self.replacement_service.list_replacements(
            self.farm_id,
            self.transaction_id,
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].credit_applied_total, Decimal("1000.00"))
        self.assertEqual(history[0].items[0].chicken_type, ChickenType.BROILER)
        self.assertEqual(history[0].items[0].bonus_quantity, Decimal("1"))

    async def test_replacement_cannot_apply_same_return_credit_twice(self):
        await self._create_ten_layer_return()
        request = cast(Any, PurchaseReplacementCreateRequest).model_validate(
            {
                "purchase_return_id": str(self.return_repository.returns[0].id),
                "replacement_date": date(2026, 10, 10),
                "items": [
                    {
                        "purchase_return_item_id": str(self.return_repository.items[0].id),
                        "batch_id": str(self.broiler_batch_id),
                        "quantity_received": 10,
                        "credit_applied_amount": "1000.00",
                        "block_allocations": [
                            {"block_id": str(self.blocks[3].id), "quantity": 10},
                        ],
                    }
                ],
            }
        )
        await self.replacement_service.create_replacement(
            self.farm_id,
            self.transaction_id,
            request,
        )
        request.items[0].credit_applied_amount = Decimal("1.00")

        with self.assertRaises(ConflictError):
            await self.replacement_service.create_replacement(
                self.farm_id,
                self.transaction_id,
                request,
            )
        self.assertEqual(len(self.replacement_repository.replacements), 1)

    async def test_replacement_cannot_reuse_credit_consumed_by_settlement(self):
        await self._create_ten_layer_return()
        self.transaction.settlements.append(
            SimpleNamespace(
                direction="contact_to_farm",
                total_value=Decimal("600.00"),
            )
        )
        request = cast(Any, PurchaseReplacementCreateRequest).model_validate(
            {
                "purchase_return_id": str(self.return_repository.returns[0].id),
                "replacement_date": date(2026, 10, 10),
                "items": [
                    {
                        "purchase_return_item_id": str(self.return_repository.items[0].id),
                        "batch_id": str(self.broiler_batch_id),
                        "quantity_received": 10,
                        "credit_applied_amount": "401.00",
                        "block_allocations": [
                            {"block_id": str(self.blocks[3].id), "quantity": 10},
                        ],
                    }
                ],
            }
        )

        with self.assertRaises(ConflictError):
            await self.replacement_service.create_replacement(
                self.farm_id,
                self.transaction_id,
                request,
            )

        self.assertEqual(self.replacement_repository.replacements, [])


if __name__ == "__main__":
    unittest.main()

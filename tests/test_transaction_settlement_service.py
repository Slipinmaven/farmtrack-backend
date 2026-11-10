import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import (
    ChickenBatchStatus,
    ChickenType,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.transaction_settlement import TransactionSettlementCreateRequest
from app.services.transaction_settlement_service import TransactionSettlementService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        pass


class FakeSettlementRepository:
    def __init__(self):
        self.records = []

    async def create(self, data):
        record = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            **data,
        )
        self.records.append(record)
        return record

    async def list_by_transaction(self, transaction_id):
        return [
            record
            for record in self.records
            if record.transaction_id == transaction_id
        ]


class FakeInventoryService:
    def __init__(self):
        self.movements = []

    async def append_movement(self, **movement):
        self.movements.append(movement)


class FakeChickenBatchRepository:
    def __init__(self):
        self.batches = {}

    async def get_by_id(self, farm_id, batch_id):
        return self.batches.get(batch_id)

    async def create(self, farm_id, data):
        batch = SimpleNamespace(id=uuid4(), farm_id=farm_id, **data)
        self.batches[batch.id] = batch
        return batch


class FakeBatchBlockRepository:
    def __init__(self):
        self.rows = {}

    async def get_total_quantity_by_block(self, block_id):
        return sum(
            row.quantity
            for (_, candidate_block_id), row in self.rows.items()
            if candidate_block_id == block_id
        )

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.rows.get((batch_id, block_id))

    async def create(self, data):
        row = SimpleNamespace(id=uuid4(), **data)
        self.rows[(data["batch_id"], data["block_id"])] = row
        return row

    async def update(self, row):
        return row


class FakeActivityService:
    async def record(self, **event):
        pass


class TransactionSettlementServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm = SimpleNamespace(id=uuid4(), owner_id=uuid4())
        self.transaction_id = uuid4()
        self.transaction = SimpleNamespace(
            id=self.transaction_id,
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            reference_number="SL-100",
            items=[SimpleNamespace(total_amount=Decimal("100.00"))],
        )
        self.settlements = FakeSettlementRepository()
        self.inventory = FakeInventoryService()
        self.product = SimpleNamespace(
            id=uuid4(),
            name="Layer feed",
            product_type=ProductType.FEED,
        )
        self.product_unit = SimpleNamespace(
            unit_id=uuid4(),
            conversion_factor=Decimal("12"),
            unit=SimpleNamespace(name="Bag", abbreviation="bag"),
        )
        self.base_unit = SimpleNamespace(
            id=uuid4(),
            name="Kilogram",
            abbreviation="kg",
        )
        self.blocks = {
            block_id: SimpleNamespace(
                id=block_id,
                name=f"Block {index}",
                is_active=True,
                capacity=100,
                over_capacity_limit=0,
            )
            for index, block_id in enumerate((uuid4(), uuid4()), start=1)
        }
        self.chicken_batch_repository = FakeChickenBatchRepository()
        self.batch_block_repository = FakeBatchBlockRepository()
        self.service = TransactionSettlementService(
            transaction_repository=SimpleNamespace(
                get_by_id_for_update=self.get_transaction,
                get_by_id=self.get_transaction,
            ),
            settlement_repository=self.settlements,
            payment_repository=SimpleNamespace(
                list_by_transaction=self.list_payments,
            ),
            refund_repository=SimpleNamespace(
                get_total_by_transaction=self.zero,
            ),
            supplier_refund_repository=SimpleNamespace(
                get_total_by_transaction=self.zero,
            ),
            sale_return_repository=SimpleNamespace(
                get_total_credit_by_transaction=self.zero,
                get_credited_quantities_by_item=self.empty_return_quantities,
            ),
            purchase_return_repository=SimpleNamespace(
                get_total_credit_by_transaction=self.zero,
            ),
            replacement_repository=SimpleNamespace(
                get_total_credit_applied_by_transaction=self.zero,
            ),
            product_repository=SimpleNamespace(
                get_by_id=self.get_product,
            ),
            product_unit_repository=SimpleNamespace(
                get_by_product_and_unit=self.get_product_unit,
                get_base_unit_for_product=self.get_base_unit,
            ),
            movement_repository=SimpleNamespace(get_balance=self.get_stock),
            chicken_batch_repository=self.chicken_batch_repository,
            chicken_batch_name_counter_repository=SimpleNamespace(
                allocate_next_number=self.allocate_batch_number,
            ),
            block_repository=SimpleNamespace(
                get_by_id_for_update=self.get_block,
            ),
            batch_block_repository=self.batch_block_repository,
            inventory_service=self.inventory,
            unit_of_work=FakeUnitOfWork(),
            activity_service=FakeActivityService(),
        )

    async def get_transaction(self, farm_id, transaction_id):
        return self.transaction if transaction_id == self.transaction_id else None

    async def list_payments(self, transaction_id):
        return [SimpleNamespace(amount=Decimal("40.00"))]

    async def zero(self, transaction_id):
        return Decimal("0.00")

    async def empty_return_quantities(self, transaction_id):
        return {}

    async def get_product(self, farm_id, product_id):
        return self.product if product_id == self.product.id else None

    async def get_product_unit(self, product_id, unit_id):
        return (
            self.product_unit
            if product_id == self.product.id and unit_id == self.product_unit.unit_id
            else None
        )

    async def get_base_unit(self, product_id):
        return self.base_unit if product_id == self.product.id else None

    async def get_stock(self, farm_id, product_id):
        return Decimal("50.000")

    async def allocate_batch_number(self, farm_id, batch_date):
        return 1

    async def get_block(self, farm_id, block_id):
        return self.blocks.get(block_id)

    async def test_mixed_customer_settlement_clears_sale_due(self):
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Settle remaining invoice",
                "lines": [
                    {
                        "kind": "cash",
                        "amount": "30.00",
                        "payment_method": "cash",
                    },
                    {
                        "kind": "service",
                        "description": "Transport provided",
                        "value": "30.00",
                    },
                ],
            }
        )

        result = await self.service.create(
            self.farm,
            self.transaction_id,
            request,
        )

        self.assertEqual(result.settlement.total_value, Decimal("60.00"))
        self.assertEqual(result.amount_paid, Decimal("100.00"))
        self.assertEqual(result.balance_due, Decimal("0.00"))
        self.assertEqual(result.credit_balance, Decimal("0.00"))
        self.assertEqual(self.inventory.movements, [])

    async def test_goods_credit_settlement_reduces_stock_in_base_units(self):
        self.transaction.items[0].total_amount = Decimal("100.00")
        self.service.payment_repository.list_by_transaction = self.list_overpaid
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "farm_to_contact",
                "settlement_date": date(2026, 10, 12),
                "reason": "Settle customer overpayment with feed",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "2",
                        "agreed_unit_value": "5.00",
                    }
                ],
            }
        )

        result = await self.service.create(
            self.farm,
            self.transaction_id,
            request,
        )

        self.assertEqual(result.settlement.total_value, Decimal("10.00"))
        self.assertEqual(result.amount_paid, Decimal("110.00"))
        self.assertEqual(result.credit_balance, Decimal("10.00"))
        self.assertEqual(self.inventory.movements[0]["quantity_delta"], Decimal("-24.000"))
        self.assertEqual(
            self.inventory.movements[0]["movement_type"].value,
            "settlement_issued",
        )

    async def test_settlement_cannot_exceed_available_due(self):
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Over limit",
                "lines": [
                    {
                        "kind": "cash",
                        "amount": "61.00",
                        "payment_method": "cash",
                    }
                ],
            }
        )

        with self.assertRaises(ConflictError):
            await self.service.create(
                self.farm,
                self.transaction_id,
                request,
            )

        self.assertEqual(self.settlements.records, [])

    async def test_purchase_farm_payment_reduces_supplier_due(self):
        self.transaction.transaction_type = TransactionType.PURCHASE
        self.transaction.items[0].total_amount = Decimal("100.00")
        self.service.payment_repository.list_by_transaction = self.no_payments
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "farm_to_contact",
                "settlement_date": date(2026, 10, 12),
                "reason": "Settle supplier balance",
                "lines": [
                    {
                        "kind": "cash",
                        "amount": "25.00",
                        "payment_method": "bank_transfer",
                    }
                ],
            }
        )

        result = await self.service.create(
            self.farm,
            self.transaction_id,
            request,
        )

        self.assertEqual(result.amount_paid, Decimal("25.00"))
        self.assertEqual(result.balance_due, Decimal("75.00"))

    async def test_chicken_goods_receipt_creates_batch_and_places_stock(self):
        self.product.product_type = ProductType.CHICKENS
        block_id = next(iter(self.blocks))
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Supplier settled credit with chickens",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "2",
                        "agreed_unit_value": "5.00",
                        "chicken_placement": {
                            "mode": "receive_new",
                            "new_batch": {
                                "chicken_type": "layers",
                                "age": 4,
                                "age_unit": "weeks",
                            },
                            "allocations": [
                                {"block_id": str(block_id), "quantity": 24}
                            ],
                        },
                    }
                ],
            }
        )

        result = await self.service.create(self.farm, self.transaction_id, request)

        batch = next(iter(self.chicken_batch_repository.batches.values()))
        self.assertEqual(batch.chicken_type, ChickenType.LAYERS)
        self.assertEqual(batch.product_id, self.product.id)
        self.assertEqual(batch.hatch_date, date(2026, 9, 14))
        self.assertEqual(batch.name, "2026 October 12 Batch 1")
        self.assertEqual(
            self.batch_block_repository.rows[(batch.id, block_id)].quantity,
            24,
        )
        self.assertEqual(
            self.inventory.movements[0]["quantity_delta"],
            Decimal("24.000"),
        )
        self.assertEqual(
            result.settlement.lines[0]["chicken_placement"]["allocations"][0][
                "batch_name"
            ],
            batch.name,
        )
        self.assertEqual(
            result.settlement.lines[0]["chicken_placement"]["new_batch"][
                "hatch_date"
            ],
            "2026-09-14",
        )

    async def test_chicken_receipt_accepts_a_custom_batch_name(self):
        self.product.product_type = ProductType.CHICKENS
        block_id = next(iter(self.blocks))
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Supplier delivered a named chicken batch",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "1",
                        "agreed_unit_value": "5.00",
                        "chicken_placement": {
                            "mode": "receive_new",
                            "new_batch": {
                                "name": "Supplier pullets",
                                "chicken_type": "layers",
                                "age": 6,
                                "age_unit": "weeks",
                            },
                            "allocations": [
                                {"block_id": str(block_id), "quantity": 12}
                            ],
                        },
                    }
                ],
            }
        )

        await self.service.create(self.farm, self.transaction_id, request)

        batch = next(iter(self.chicken_batch_repository.batches.values()))
        self.assertEqual(batch.name, "Supplier pullets")
        self.assertEqual(batch.hatch_date, date(2026, 8, 31))

    async def test_chicken_goods_issue_decrements_allocated_flock_stock(self):
        self.product.product_type = ProductType.CHICKENS
        self.service.payment_repository.list_by_transaction = self.list_overpaid
        batch = SimpleNamespace(
            id=uuid4(),
            farm_id=self.farm.id,
            name="Current layers",
            product_id=self.product.id,
            chicken_type=ChickenType.LAYERS,
            status=ChickenBatchStatus.ACTIVE,
        )
        self.chicken_batch_repository.batches[batch.id] = batch
        block_id = next(iter(self.blocks))
        self.batch_block_repository.rows[(batch.id, block_id)] = SimpleNamespace(
            id=uuid4(),
            batch_id=batch.id,
            block_id=block_id,
            quantity=30,
        )
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "farm_to_contact",
                "settlement_date": date(2026, 10, 12),
                "reason": "Settle overpayment with chickens",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "2",
                        "agreed_unit_value": "5.00",
                        "chicken_placement": {
                            "mode": "issue",
                            "allocations": [
                                {
                                    "batch_id": str(batch.id),
                                    "block_id": str(block_id),
                                    "quantity": 24,
                                }
                            ],
                        },
                    }
                ],
            }
        )

        await self.service.create(self.farm, self.transaction_id, request)

        self.assertEqual(
            self.batch_block_repository.rows[(batch.id, block_id)].quantity,
            6,
        )
        self.assertEqual(
            self.inventory.movements[0]["quantity_delta"],
            Decimal("-24.000"),
        )

    async def test_chicken_goods_issue_rejects_batch_from_another_product(self):
        self.product.product_type = ProductType.CHICKENS
        self.service.payment_repository.list_by_transaction = self.list_overpaid
        batch = SimpleNamespace(
            id=uuid4(),
            farm_id=self.farm.id,
            name="Other product layers",
            product_id=uuid4(),
            chicken_type=ChickenType.LAYERS,
            status=ChickenBatchStatus.ACTIVE,
        )
        self.chicken_batch_repository.batches[batch.id] = batch
        block_id = next(iter(self.blocks))
        self.batch_block_repository.rows[(batch.id, block_id)] = SimpleNamespace(
            id=uuid4(),
            batch_id=batch.id,
            block_id=block_id,
            quantity=30,
        )
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "farm_to_contact",
                "settlement_date": date(2026, 10, 12),
                "reason": "Settle overpayment with chickens",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "1",
                        "agreed_unit_value": "5.00",
                        "chicken_placement": {
                            "mode": "issue",
                            "allocations": [
                                {
                                    "batch_id": str(batch.id),
                                    "block_id": str(block_id),
                                    "quantity": 12,
                                }
                            ],
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ConflictError, "not linked to the selected"):
            await self.service.create(self.farm, self.transaction_id, request)

        self.assertEqual(
            self.batch_block_repository.rows[(batch.id, block_id)].quantity,
            30,
        )
        self.assertEqual(self.settlements.records, [])
        self.assertEqual(self.inventory.movements, [])

    async def test_chicken_goods_require_a_recorded_placement(self):
        self.product.product_type = ProductType.CHICKENS
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Unplaced chicken settlement",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "1",
                        "agreed_unit_value": "5.00",
                    }
                ],
            }
        )

        with self.assertRaises(ConflictError):
            await self.service.create(self.farm, self.transaction_id, request)

        self.assertEqual(self.settlements.records, [])
        self.assertEqual(self.inventory.movements, [])

    async def test_chicken_receipt_rejects_block_capacity_overflow(self):
        self.product.product_type = ProductType.CHICKENS
        block_id = next(iter(self.blocks))
        self.blocks[block_id].capacity = 10
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Receipt exceeds housing capacity",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "2",
                        "agreed_unit_value": "5.00",
                        "chicken_placement": {
                            "mode": "receive_new",
                            "new_batch": {
                                "chicken_type": "layers",
                                "age": 2,
                                "age_unit": "months",
                            },
                            "allocations": [
                                {"block_id": str(block_id), "quantity": 24}
                            ],
                        },
                    }
                ],
            }
        )

        with self.assertRaises(ConflictError):
            await self.service.create(self.farm, self.transaction_id, request)

        self.assertEqual(self.chicken_batch_repository.batches, {})
        self.assertEqual(self.settlements.records, [])
        self.assertEqual(self.inventory.movements, [])

    async def test_goods_settlement_discount_reduces_value_and_is_snapshotted(self):
        request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Settle goods with agreed discount",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "2",
                        "agreed_unit_value": "10.00",
                        "discount_type": "fixed",
                        "discount_value": "5.00",
                        "discount_reason": "Bulk purchase",
                    }
                ],
            }
        )

        result = await self.service.create(self.farm, self.transaction_id, request)

        self.assertEqual(result.settlement.total_value, Decimal("15.00"))
        goods_line = result.settlement.lines[0]
        self.assertEqual(goods_line["gross_value"], "20.00")
        self.assertEqual(goods_line["discount_amount"], "5.00")
        self.assertEqual(goods_line["discount_reason"], "Bulk purchase")
        self.assertEqual(goods_line["value"], "15.00")

    async def test_percentage_discount_is_rounded_and_cannot_exceed_line_value(self):
        percentage_request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Settle goods with percentage discount",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "2",
                        "agreed_unit_value": "10.00",
                        "discount_type": "percentage",
                        "discount_value": "10.00",
                    }
                ],
            }
        )
        result = await self.service.create(
            self.farm,
            self.transaction_id,
            percentage_request,
        )
        self.assertEqual(result.settlement.total_value, Decimal("18.00"))
        self.assertEqual(
            result.settlement.lines[0]["discount_amount"],
            "2.00",
        )

        excessive_request = TransactionSettlementCreateRequest.model_validate(
            {
                "direction": "contact_to_farm",
                "settlement_date": date(2026, 10, 12),
                "reason": "Discount exceeds goods value",
                "lines": [
                    {
                        "kind": "goods",
                        "product_id": str(self.product.id),
                        "unit_id": str(self.product_unit.unit_id),
                        "quantity": "2",
                        "agreed_unit_value": "10.00",
                        "discount_type": "fixed",
                        "discount_value": "20.01",
                    }
                ],
            }
        )
        with self.assertRaises(ConflictError):
            await self.service.create(
                self.farm,
                self.transaction_id,
                excessive_request,
            )

    async def list_overpaid(self, transaction_id):
        return [SimpleNamespace(amount=Decimal("120.00"))]

    async def no_payments(self, transaction_id):
        return []


if __name__ == "__main__":
    unittest.main()

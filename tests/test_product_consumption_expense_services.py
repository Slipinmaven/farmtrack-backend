import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import inspect

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.models.expense_payment import ExpensePayment
from app.repositories.expense_repository import ExpenseRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    PaymentMethod,
    ProductType,
)
from app.schemas.expense import (
    ExpenseCancelRequest,
    ExpenseCreateRequest,
    ExpensePaymentCreateRequest,
    ExpenseRefundCreateRequest,
    ExpenseUpdateRequest,
)
from app.schemas.product_consumption import (
    ProductConsumptionBatchCreateRequest,
    ProductConsumptionCreateRequest,
)
from app.services.expense_service import ExpenseService
from app.services.product_consumption_service import ProductConsumptionService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        pass


class FakeActivityService:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class FakeProductRepository:
    def __init__(self, products):
        self.products = products

    async def get_by_id(self, farm_id, product_id):
        product = self.products.get(product_id)
        if product is None or product.farm_id != farm_id:
            return None
        return product


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


class FakeBatchRepository:
    def __init__(self, batches):
        self.batches = batches

    async def get_by_id(self, farm_id, batch_id):
        batch = self.batches.get(batch_id)
        if batch is None or batch.farm_id != farm_id:
            return None
        return batch


class FakeBatchBlockRepository:
    def __init__(self, assignments):
        self.assignments = assignments

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.assignments.get((batch_id, block_id))


class FakeProductConsumptionRepository:
    def __init__(self):
        self.rows = []

    async def create(self, farm_id, data):
        row = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **data,
        )
        self.rows.append(row)
        return row

    async def list_by_farm(self, farm_id, *, offset=0, limit=50, **filters):
        return [row for row in self.rows if row.farm_id == farm_id]


class FakeInventoryService:
    def __init__(self):
        self.movements = []

    async def append_movement(self, **movement):
        self.movements.append(movement)


class FakeContactRepository:
    def __init__(self, contacts):
        self.contacts = contacts

    async def get_by_id(self, farm_id, contact_id):
        contact = self.contacts.get(contact_id)
        if contact is None or contact.farm_id != farm_id:
            return None
        return contact


class FakeExpenseRepository:
    def __init__(self):
        self.rows = []

    async def create(self, farm_id, data):
        data.setdefault("contact_id", None)
        data.setdefault("block_id", None)
        data.setdefault("receipt_reference", None)
        data.setdefault("reference_number", None)
        data.setdefault("notes", None)
        row = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            payments=[],
            contact=None,
            block=None,
            canceled_at=None,
            cancellation_reason=None,
            purchase_transaction_id=None,
            purchase_transaction=None,
            **data,
        )
        self.rows.append(row)
        return row

    async def list_by_farm(self, farm_id, *, offset=0, limit=50, **filters):
        rows = [row for row in self.rows if row.farm_id == farm_id]
        return rows[offset : offset + limit], len(rows)

    async def get_by_id_for_update(self, farm_id, expense_id):
        return next(
            (
                row
                for row in self.rows
                if row.farm_id == farm_id and row.id == expense_id
            ),
            None,
        )

    async def summarize_by_farm(self, farm_id, *, from_date=None, to_date=None):
        totals = {}
        for expense in self.rows:
            if expense.farm_id != farm_id or expense.canceled_at is not None:
                continue
            if from_date and expense.expense_date < from_date:
                continue
            if to_date and expense.expense_date > to_date:
                continue
            net_paid = sum(
                (
                    payment.amount
                    if payment.kind == "payment"
                    else -payment.amount
                    for payment in expense.payments
                ),
                Decimal("0.00"),
            )
            paid = min(max(net_paid, Decimal("0.00")), expense.amount)
            previous = totals.get(
                expense.category,
                (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), 0),
            )
            totals[expense.category] = (
                previous[0] + expense.amount,
                previous[1] + paid,
                previous[2] + max(expense.amount - paid, Decimal("0.00")),
                previous[3] + 1,
            )
        return [
            (key, count, amount, paid, balance)
            for key, (amount, paid, balance, count) in totals.items()
        ]


class FakeExpenseCategoryRepository:
    def __init__(self, farm_id):
        self.categories = [
            SimpleNamespace(
                id=uuid4(),
                farm_id=farm_id,
                key="feed_and_nutrition",
                name="Feed and nutrition",
                is_default=True,
                is_active=True,
            )
        ]

    async def get_by_key(self, farm_id, key):
        return next(
            (
                category
                for category in self.categories
                if category.farm_id == farm_id and category.key == key
            ),
            None,
        )

    async def list_by_farm(self, farm_id, include_inactive=False):
        return [
            category
            for category in self.categories
            if category.farm_id == farm_id
            and (include_inactive or category.is_active)
        ]

    async def create(self, farm_id, data):
        category = SimpleNamespace(id=uuid4(), farm_id=farm_id, **data)
        self.categories.append(category)
        return category


class FakeExpensePaymentRepository:
    def __init__(self):
        self.rows = []

    async def create(self, expense_id, data):
        data.setdefault("reason", None)
        payment = SimpleNamespace(
            id=uuid4(),
            expense_id=expense_id,
            created_at=datetime.now(timezone.utc),
            **data,
        )
        self.rows.append(payment)
        return payment

    async def list_by_expense(self, expense_id):
        return [row for row in self.rows if row.expense_id == expense_id]


class ProductConsumptionExpenseServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.farm = SimpleNamespace(id=self.farm_id, owner_id=uuid4())
        self.product_id = uuid4()
        self.unit_id = uuid4()
        self.block_id = uuid4()
        self.batch_id = uuid4()
        self.contact_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            farm_id=self.farm_id,
            name="Layer feed",
            is_active=True,
            product_type=ProductType.FEED,
        )
        self.product_unit = SimpleNamespace(
            product_id=self.product_id,
            unit_id=self.unit_id,
            conversion_factor=Decimal("25.000"),
            unit=SimpleNamespace(name="sack", abbreviation="sack"),
            is_base_unit=True,
        )
        self.block = SimpleNamespace(
            id=self.block_id,
            farm_id=self.farm_id,
            name="Layer house",
        )
        self.batch = SimpleNamespace(
            id=self.batch_id,
            farm_id=self.farm_id,
            name="Layer flock",
        )
        self.contact = SimpleNamespace(
            id=self.contact_id,
            farm_id=self.farm_id,
            name="Farm supplier",
        )
        self.assignment = SimpleNamespace(
            batch_id=self.batch_id,
            block_id=self.block_id,
            quantity=50,
        )
        self.activity_service = FakeActivityService()
        self.consumption_repository = FakeProductConsumptionRepository()
        self.inventory_service = FakeInventoryService()
        self.consumption_service = ProductConsumptionService(
            consumption_repository=cast(Any, self.consumption_repository),
            product_repository=cast(Any, FakeProductRepository({self.product_id: self.product})),
            product_unit_repository=cast(
                Any,
                FakeProductUnitRepository({(self.product_id, self.unit_id): self.product_unit}),
            ),
            block_repository=cast(Any, FakeBlockRepository({self.block_id: self.block})),
            chicken_batch_repository=cast(Any, FakeBatchRepository({self.batch_id: self.batch})),
            batch_block_repository=cast(
                Any,
                FakeBatchBlockRepository({(self.batch_id, self.block_id): self.assignment}),
            ),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
            inventory_service=cast(Any, self.inventory_service),
        )
        self.expense_repository = FakeExpenseRepository()
        self.expense_payment_repository = FakeExpensePaymentRepository()
        self.expense_service = ExpenseService(
            expense_repository=cast(Any, self.expense_repository),
            contact_repository=cast(
                Any,
                FakeContactRepository({self.contact_id: self.contact}),
            ),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
            category_repository=cast(
                Any,
                FakeExpenseCategoryRepository(self.farm_id),
            ),
            payment_repository=cast(Any, self.expense_payment_repository),
            block_repository=cast(
                Any,
                FakeBlockRepository({self.block_id: self.block}),
            ),
        )

    def _consumption_request(self, **overrides):
        data = {
            "product_id": str(self.product_id),
            "unit_id": str(self.unit_id),
            "allocations": [
                {
                    "quantity": "2.000",
                    "block_id": str(self.block_id),
                    "batch_id": str(self.batch_id),
                }
            ],
            "consumption_date": date(2026, 10, 10),
            "notes": "Morning feed",
        }
        data.update(overrides)
        return cast(Any, ProductConsumptionBatchCreateRequest).model_validate(data)

    def _expense_request(self, **overrides):
        data = {
            "name": "Layer feed",
            "category": "feed_and_nutrition",
            "amount": "1250.50",
            "expense_date": date(2026, 10, 10),
            "contact_id": str(self.contact_id),
            "initial_payment": {
                "amount": "1250.50",
                "payment_date": date(2026, 10, 10),
                "payment_method": PaymentMethod.MPESA.value,
                "reference_number": "MP-101",
            },
            "notes": "Feed delivery",
        }
        data.update(overrides)
        return cast(Any, ExpenseCreateRequest).model_validate(data)

    async def test_product_consumption_snapshots_conversion_and_context(self):
        response = await self.consumption_service.record_consumptions(
            self.farm,
            self._consumption_request(),
        )

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0].quantity_in_base_unit, Decimal("50.000"))
        self.assertEqual(response[0].block_id, self.block_id)
        self.assertEqual(response[0].batch_id, self.batch_id)
        self.assertEqual(len(self.consumption_repository.rows), 1)
        self.assertEqual(
            self.activity_service.events[-1]["activity_type"],
            ActivityType.PRODUCT_CONSUMPTION_RECORDED,
        )
        self.assertEqual(
            self.activity_service.events[-1]["entity_type"],
            ActivityEntityType.PRODUCT_CONSUMPTION,
        )
        self.assertEqual(len(self.inventory_service.movements), 1)
        self.assertEqual(
            self.inventory_service.movements[0]["quantity_delta"],
            Decimal("-50.000"),
        )
        self.assertEqual(
            self.inventory_service.movements[0]["movement_type"],
            "consumption",
        )
        activity_details = self.activity_service.events[-1]["details"]
        self.assertEqual(activity_details["unit_abbreviation"], "sack")
        self.assertEqual(activity_details["base_unit_name"], "sack")
        self.assertEqual(self.assignment.quantity, 50)

    async def test_single_product_consumption_endpoint_service_contract(self):
        request = cast(Any, ProductConsumptionCreateRequest).model_validate(
            {
                "product_id": str(self.product_id),
                "unit_id": str(self.unit_id),
                "quantity": "2.000",
                "block_id": str(self.block_id),
                "batch_id": str(self.batch_id),
                "consumption_date": date(2026, 10, 10),
                "notes": "Morning feed",
            }
        )
        response = await self.consumption_service.record_consumption(
            self.farm,
            request,
        )

        self.assertEqual(response.quantity_in_base_unit, Decimal("50.000"))
        self.assertEqual(response.block_id, self.block_id)
        self.assertEqual(response.batch_id, self.batch_id)

    async def test_product_consumption_rejects_invalid_product_unit_and_batch_location_pair(self):
        with self.assertRaises(ConflictError):
            await self.consumption_service.record_consumptions(
                self.farm,
                self._consumption_request(unit_id=str(uuid4())),
            )

        other_block_id = uuid4()
        block_repository = FakeBlockRepository(
            {
                self.block_id: self.block,
                other_block_id: SimpleNamespace(id=other_block_id, farm_id=self.farm_id),
            }
        )
        service = ProductConsumptionService(
            consumption_repository=cast(Any, self.consumption_repository),
            product_repository=cast(Any, FakeProductRepository({self.product_id: self.product})),
            product_unit_repository=cast(
                Any,
                FakeProductUnitRepository({(self.product_id, self.unit_id): self.product_unit}),
            ),
            block_repository=cast(Any, block_repository),
            chicken_batch_repository=cast(Any, FakeBatchRepository({self.batch_id: self.batch})),
            batch_block_repository=cast(Any, FakeBatchBlockRepository({})),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
        )
        with self.assertRaises(ConflictError):
            await service.record_consumptions(
                self.farm,
                self._consumption_request(
                    allocations=[
                        {
                            "quantity": "2.000",
                            "block_id": str(other_block_id),
                            "batch_id": str(self.batch_id),
                        }
                    ]
                ),
            )
        self.assertEqual(self.consumption_repository.rows, [])

    async def test_product_consumption_splits_quantities_across_optional_locations(self):
        response = await self.consumption_service.record_consumptions(
            self.farm,
            self._consumption_request(
                allocations=[
                    {"quantity": "0.400", "block_id": str(self.block_id)},
                    {
                        "quantity": "0.600",
                        "block_id": str(self.block_id),
                        "batch_id": str(self.batch_id),
                    },
                    {"quantity": "1.000", "batch_id": str(self.batch_id)},
                    {"quantity": "0.500"},
                ],
            ),
        )

        self.assertEqual(len(response), 4)
        self.assertEqual(
            [record.quantity_in_base_unit for record in response],
            [
                Decimal("10.000"),
                Decimal("15.000"),
                Decimal("25.000"),
                Decimal("12.500"),
            ],
        )
        self.assertEqual(response[0].block_id, self.block_id)
        self.assertIsNone(response[0].batch_id)
        self.assertIsNone(response[2].block_id)
        self.assertEqual(response[2].batch_id, self.batch_id)
        self.assertIsNone(response[3].block_id)
        self.assertIsNone(response[3].batch_id)
        self.assertEqual(len(self.inventory_service.movements), 4)
        self.assertEqual(
            sum(
                (
                    -movement["quantity_delta"]
                    for movement in self.inventory_service.movements
                ),
                Decimal("0"),
            ),
            Decimal("62.500"),
        )

    async def test_product_consumption_rejects_unassigned_batch_block_pair(self):
        service = ProductConsumptionService(
            consumption_repository=cast(Any, self.consumption_repository),
            product_repository=cast(Any, FakeProductRepository({self.product_id: self.product})),
            product_unit_repository=cast(
                Any,
                FakeProductUnitRepository({(self.product_id, self.unit_id): self.product_unit}),
            ),
            block_repository=cast(Any, FakeBlockRepository({self.block_id: self.block})),
            chicken_batch_repository=cast(Any, FakeBatchRepository({self.batch_id: self.batch})),
            batch_block_repository=cast(Any, FakeBatchBlockRepository({})),
            unit_of_work=cast(Any, FakeUnitOfWork()),
            activity_service=cast(Any, self.activity_service),
            inventory_service=cast(Any, self.inventory_service),
        )

        with self.assertRaises(ConflictError):
            await service.record_consumptions(
                self.farm,
                self._consumption_request(),
            )
        self.assertEqual(self.consumption_repository.rows, [])

    async def test_product_consumption_rejects_chickens_and_eggs(self):
        for product_type in (ProductType.CHICKENS, ProductType.EGGS):
            self.product.product_type = product_type
            with self.subTest(product_type=product_type):
                with self.assertRaises(ConflictError):
                    await self.consumption_service.record_consumptions(
                        self.farm,
                        self._consumption_request(),
                    )
        self.assertEqual(self.consumption_repository.rows, [])

    async def test_expense_records_payment_details_and_activity(self):
        response = await self.expense_service.create_expense(
            self.farm,
            self._expense_request(),
        )

        self.assertEqual(response.amount, Decimal("1250.50"))
        self.assertEqual(response.category, "feed_and_nutrition")
        self.assertEqual(response.payments[0].payment_method, PaymentMethod.MPESA)
        self.assertEqual(response.amount_paid, Decimal("1250.50"))
        self.assertEqual(response.contact_id, self.contact_id)
        self.assertEqual(
            self.activity_service.events[-1]["activity_type"],
            ActivityType.EXPENSE_RECORDED,
        )
        self.assertEqual(
            self.activity_service.events[-1]["entity_type"],
            ActivityEntityType.EXPENSE,
        )

    async def test_purchase_linked_expense_cannot_be_edited_from_expenses(self):
        response = await self.expense_service.create_expense(
            self.farm,
            self._expense_request(),
        )
        self.expense_repository.rows[0].purchase_transaction_id = uuid4()

        with self.assertRaisesRegex(ConflictError, "linked to a purchase"):
            await self.expense_service.update_expense(
                self.farm,
                response.id,
                ExpenseUpdateRequest(notes="Manual update"),
            )

    async def test_expense_rejects_contact_from_another_farm(self):
        self.contact.farm_id = uuid4()
        with self.assertRaises(ResourceNotFoundError):
            await self.expense_service.create_expense(
                self.farm,
                self._expense_request(),
            )
        self.assertEqual(self.expense_repository.rows, [])

    async def test_expense_requires_reference_for_non_cash_payment(self):
        with self.assertRaises(ValidationError):
            self._expense_request(
                initial_payment={
                    "amount": "10.00",
                    "payment_date": date(2026, 10, 10),
                    "payment_method": PaymentMethod.MPESA.value,
                    "reference_number": None,
                }
            )

        cash_request = self._expense_request(
            initial_payment={
                "amount": "10.00",
                "payment_date": date(2026, 10, 10),
                "payment_method": PaymentMethod.CASH.value,
                "reference_number": None,
            },
        )
        response = await self.expense_service.create_expense(self.farm, cash_request)
        self.assertIsNone(response.payments[0].reference_number)

    async def test_expense_payment_tracks_partial_balance_and_blocks_overpayment(self):
        response = await self.expense_service.create_expense(
            self.farm,
            self._expense_request(
                initial_payment={
                    "amount": "400.00",
                    "payment_date": date(2026, 10, 10),
                    "payment_method": PaymentMethod.CASH.value,
                }
            ),
        )
        self.assertEqual(response.payment_status, "partial")
        self.assertEqual(response.balance_due, Decimal("850.50"))

        payment = ExpensePaymentCreateRequest.model_validate(
            {
                "amount": "850.50",
                "payment_date": date(2026, 10, 11),
                "payment_method": PaymentMethod.MPESA.value,
                "reference_number": "MP-102",
            }
        )
        paid = await self.expense_service.record_payment(
            self.farm,
            response.id,
            payment,
        )
        self.assertEqual(paid.payment_status, "paid")
        self.assertEqual(paid.balance_due, Decimal("0.00"))
        self.assertEqual(len(paid.payments), 2)
        self.assertEqual(
            self.activity_service.events[-1]["details"]["event_action"],
            "payment_recorded",
        )

        with self.assertRaises(ConflictError):
            await self.expense_service.record_payment(
                self.farm,
                response.id,
                ExpensePaymentCreateRequest.model_validate(
                    {
                        "amount": "0.01",
                        "payment_date": date(2026, 10, 12),
                        "payment_method": PaymentMethod.CASH.value,
                    }
                ),
            )

    async def test_paid_expense_cannot_be_lowered_until_payments_are_refunded(self):
        response = await self.expense_service.create_expense(
            self.farm,
            self._expense_request(),
        )
        with self.assertRaises(ConflictError):
            await self.expense_service.update_expense(
                self.farm,
                response.id,
                ExpenseUpdateRequest(amount=Decimal("1000.00")),
            )

    async def test_expense_requires_refund_before_cancellation_and_keeps_audit_rows(self):
        response = await self.expense_service.create_expense(
            self.farm,
            self._expense_request(),
        )
        cancel_request = ExpenseCancelRequest(reason="Duplicate entry")
        with self.assertRaises(ConflictError):
            await self.expense_service.cancel_expense(
                self.farm,
                response.id,
                cancel_request,
            )

        refund = ExpenseRefundCreateRequest.model_validate(
            {
                "amount": "1250.50",
                "payment_date": date(2026, 10, 12),
                "payment_method": PaymentMethod.CASH.value,
                "reason": "Supplier returned payment",
            }
        )
        refunded = await self.expense_service.record_refund(
            self.farm,
            response.id,
            refund,
        )
        self.assertEqual(refunded.amount_paid, Decimal("0.00"))
        self.assertEqual(len(refunded.payments), 2)

        canceled = await self.expense_service.cancel_expense(
            self.farm,
            response.id,
            cancel_request,
        )
        self.assertEqual(canceled.payment_status, "cancelled")
        self.assertEqual(len(canceled.payments), 2)
        self.assertEqual(canceled.cancellation_reason, "Duplicate entry")
        self.assertEqual(
            self.activity_service.events[-1]["details"]["event_action"],
            "cancelled",
        )

    async def test_expense_categories_seed_defaults_for_farms_and_map_from_orm(self):
        categories = await self.expense_service.list_categories(self.farm)
        keys = {category.key for category in categories}
        self.assertIn("feed_and_nutrition", keys)
        self.assertIn("equipment", keys)
        self.assertIn("other", keys)

    async def test_expense_list_returns_page_and_total_count(self):
        await self.expense_service.create_expense(
            self.farm,
            self._expense_request(name="Feed delivery one"),
        )
        await self.expense_service.create_expense(
            self.farm,
            self._expense_request(name="Feed delivery two"),
        )

        page = await self.expense_service.list_expenses(
            self.farm,
            offset=1,
            limit=1,
        )

        self.assertEqual(page.total_count, 2)
        self.assertEqual(page.offset, 1)
        self.assertEqual(page.limit, 1)
        self.assertEqual(len(page.items), 1)

    async def test_expense_summary_aggregates_for_reports(self):
        await self.expense_service.create_expense(
            self.farm,
            self._expense_request(
                amount="100.00",
                initial_payment={
                    "amount": "40.00",
                    "payment_date": date(2026, 10, 10),
                    "payment_method": PaymentMethod.CASH.value,
                },
            ),
        )

        summary = await self.expense_service.get_expense_summary(self.farm)

        self.assertEqual(summary.expense_count, 1)
        self.assertEqual(summary.total_amount, Decimal("100.00"))
        self.assertEqual(summary.amount_paid, Decimal("40.00"))
        self.assertEqual(summary.balance_due, Decimal("60.00"))
        self.assertEqual(summary.categories[0].name, "Feed and nutrition")

    async def test_schemas_reject_nonpositive_consumption_and_expense(self):
        with self.assertRaises(ValidationError):
            self._consumption_request(quantity="0")
        with self.assertRaises(ValidationError):
            self._expense_request(amount="0")
        with self.assertRaises(ValidationError):
            ExpenseUpdateRequest.model_validate({"name": None})


class ExpenseRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_expense_payment_collection_is_loaded_before_append(self):
        class FakeSession:
            def add(self, instance):
                self.instance = instance

            async def flush(self):
                pass

        session = FakeSession()
        repository = ExpenseRepository(cast(Any, session))
        expense = await repository.create(
            uuid4(),
            {
                "name": "Feed",
                "category": "feed_and_nutrition",
                "amount": Decimal("100.00"),
                "expense_date": date(2026, 10, 19),
                "payment_method": PaymentMethod.CASH,
            },
        )

        self.assertEqual(inspect(expense).attrs.payments.loaded_value, [])
        payment = ExpensePayment(
            expense_id=expense.id,
            kind="payment",
            amount=Decimal("40.00"),
            payment_date=date(2026, 10, 19),
            payment_method=PaymentMethod.CASH,
        )
        expense.payments.append(payment)

        self.assertEqual(expense.payments, [payment])


if __name__ == "__main__":
    unittest.main()

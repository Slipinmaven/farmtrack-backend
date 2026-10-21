import unittest
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.schemas.chicken_purchase import ChickenPurchaseRequest
from app.schemas.chicken_sale import ChickenSaleRequest
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ContactRoleEnum,
    ChickenType,
    PaymentMethod,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.payment import PaymentCreate
from app.schemas.transaction import TransactionCreate
from app.services.transaction_reference import farm_local_date
from app.services.chicken_purchase_service import ChickenPurchaseService
from app.services.transaction_service import TransactionService


class FakeExpenseRepository:
    def __init__(self):
        self.rows = []

    async def create(self, farm_id, data):
        expense = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            payments=[],
            **data,
        )
        self.rows.append(expense)
        return expense

    async def get_by_purchase_transaction(self, transaction_id):
        return next(
            (
                expense
                for expense in self.rows
                if expense.purchase_transaction_id == transaction_id
            ),
            None,
        )


class FakeExpensePaymentRepository:
    async def create(self, expense_id, data):
        return SimpleNamespace(
            id=uuid4(),
            expense_id=expense_id,
            created_at=datetime.now(),
            **data,
        )


class FakeExpenseCategoryRepository:
    def __init__(self):
        self.categories = {}

    async def get_by_key(self, farm_id, key):
        return self.categories.get((farm_id, key))

    async def create(self, farm_id, data):
        category = SimpleNamespace(farm_id=farm_id, **data)
        self.categories[(farm_id, data["key"])] = category
        return category


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


class FakeTransactionRepository:
    def __init__(self, transaction=None):
        self.transaction = transaction

    async def create(self, farm_id, data):
        now = datetime.now()
        data.setdefault("contact_id", None)
        data.setdefault("reference_number", None)
        data.setdefault("notes", None)
        data.setdefault("transaction_time", None)
        data.setdefault("discount_type", None)
        data.setdefault("discount_value", Decimal("0.00"))
        data.setdefault("discount_amount", Decimal("0.00"))
        data.setdefault("discount_reason", None)
        self.transaction = SimpleNamespace(
            id=uuid4(),
            farm_id=farm_id,
            created_at=now,
            updated_at=now,
            **data,
        )
        return self.transaction

    async def get_by_id_for_update(self, farm_id, transaction_id):
        if self.transaction is None or self.transaction.id != transaction_id:
            return None
        return self.transaction


class FakeTransactionItemRepository:
    def __init__(self):
        self.created = []

    async def create(self, data):
        data.setdefault("chicken_type", None)
        item = SimpleNamespace(id=uuid4(), notes=None, **data)
        self.created.append(item)
        return item


class FakePaymentRepository:
    def __init__(self, payments=None):
        self.payments = list(payments or [])

    async def create(self, data):
        data.setdefault("payment_time", None)
        data.setdefault("reference_number", None)
        data.setdefault("notes", None)
        payment = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            **data,
        )
        self.payments.append(payment)
        return payment

    async def list_by_transaction(self, transaction_id):
        return [payment for payment in self.payments if payment.transaction_id == transaction_id]


class FakeCreditRepository:
    def __init__(self, total=Decimal("0.00")):
        self.total = total

    async def get_total_credit_by_transaction(self, transaction_id):
        return self.total


class FakeRefundRepository:
    def __init__(self, total=Decimal("0.00")):
        self.total = total

    async def get_total_by_transaction(self, transaction_id):
        return self.total


class FakeContactRepository:
    def __init__(self, contact=None):
        self.contact = contact

    async def get_by_id(self, farm_id, contact_id):
        if self.contact is None or self.contact.id != contact_id:
            return None
        return self.contact


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


class FakeFarmSettingsRepository:
    async def get_farm_settings(self, farm_id):
        return SimpleNamespace(timezone="Pacific/Kiritimati")


class FakeTransactionReferenceCounterRepository:
    def __init__(self):
        self.counters = {}

    async def allocate_next_number(self, farm_id, reference_type, reference_date):
        key = (farm_id, reference_type, reference_date)
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


class TransactionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.supplier_id = uuid4()
        self.contact_repository = FakeContactRepository(
            SimpleNamespace(
                id=self.supplier_id,
                name="Farm supplier",
                contact_roles=[SimpleNamespace(role=ContactRoleEnum.SUPPLIER)],
            )
        )
        self.products = {
            uuid4(): SimpleNamespace(
                id=None,
                farm_id=self.farm_id,
                product_type=ProductType.CHICKENS,
                is_active=True,
                is_sellable=True,
            )
            for _ in range(2)
        }
        for index, (product_id, product) in enumerate(self.products.items(), start=1):
            product.id = product_id
            product.name = f"Product {index}"
        product_ids = list(self.products)
        self.unit_ids = [uuid4(), uuid4()]
        self.product_units = {
            (product_ids[0], self.unit_ids[0]): SimpleNamespace(
                conversion_factor=Decimal("1"),
                unit=SimpleNamespace(name="bird", abbreviation="bird"),
            ),
            (product_ids[1], self.unit_ids[1]): SimpleNamespace(
                conversion_factor=Decimal("50"),
                unit=SimpleNamespace(name="sack", abbreviation="sack"),
            ),
        }
        self.transaction_item_repository = FakeTransactionItemRepository()
        self.payment_repository = FakePaymentRepository()
        self.credit_repository = FakeCreditRepository()
        self.refund_repository = FakeRefundRepository()
        self.activity_service = FakeActivityService()
        self.reference_counter_repository = FakeTransactionReferenceCounterRepository()
        self.expense_repository = FakeExpenseRepository()
        self.expense_payment_repository = FakeExpensePaymentRepository()
        self.expense_category_repository = FakeExpenseCategoryRepository()
        self.service = TransactionService(
            transaction_repository=FakeTransactionRepository(),
            transaction_item_repository=self.transaction_item_repository,
            transaction_payment_repository=self.payment_repository,
            contact_repository=self.contact_repository,
            product_repository=FakeProductRepository(self.products),
            product_unit_repository=FakeProductUnitRepository(self.product_units),
            unit_of_work=FakeUnitOfWork(),
            activity_service=self.activity_service,
            sale_return_repository=self.credit_repository,
            transaction_refund_repository=self.refund_repository,
            farm_settings_repository=FakeFarmSettingsRepository(),
            transaction_reference_counter_repository=self.reference_counter_repository,
            expense_repository=self.expense_repository,
            expense_payment_repository=self.expense_payment_repository,
            expense_category_repository=self.expense_category_repository,
        )
        self.product_ids = product_ids

    def _purchase_data(
        self,
        payments=None,
        transaction_date=date(2026, 10, 9),
    ):
        return TransactionCreate(
            transaction_type=TransactionType.PURCHASE,
            transaction_date=transaction_date,
            contact_id=self.supplier_id,
            items=[
                {
                    "product_id": self.product_ids[0],
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": self.unit_ids[0],
                    "quantity": 400,
                    "unit_price": Decimal("150.00"),
                },
                {
                    "product_id": self.product_ids[1],
                    "chicken_type": ChickenType.BROILER,
                    "unit_id": self.unit_ids[1],
                    "quantity": 4,
                    "unit_price": Decimal("2500.00"),
                },
            ],
            payments=payments or [],
        )

    async def test_multiple_items_and_payments_calculate_cost_and_balance(self):
        purchase = await self.service.create_transaction(
            self.farm_id,
            self._purchase_data(
                [
                    PaymentCreate(
                        amount=Decimal("20000.00"),
                        payment_date=date(2026, 10, 9),
                        payment_method="cash",
                    ),
                    PaymentCreate(
                        amount=Decimal("5000.00"),
                        payment_date=date(2026, 10, 9),
                        payment_method="mpesa",
                    ),
                ]
            ),
        )

        self.assertEqual(purchase.transaction_total, Decimal("70000.00"))
        self.assertEqual(purchase.amount_paid, Decimal("25000.00"))
        self.assertEqual(purchase.balance_due, Decimal("45000.00"))
        self.assertEqual(purchase.credit_balance, Decimal("0.00"))
        self.assertEqual(purchase.reference_number, "PUR-20261009-0001")
        self.assertEqual(purchase.items[1].conversion_factor, Decimal("50"))
        self.assertEqual(purchase.items[1].ordered_base_quantity, Decimal("200"))
        self.assertEqual(purchase.items[1].chicken_type, ChickenType.BROILER)
        self.assertEqual(len(purchase.payments), 2)
        self.assertEqual(
            [item.total_amount for item in purchase.items],
            [Decimal("60000.00"), Decimal("10000.00")],
        )
        self.assertEqual(self.activity_service.events[0]["activity_type"], ActivityType.TRANSACTION_CREATED)
        self.assertEqual(self.activity_service.events[0]["entity_type"], ActivityEntityType.TRANSACTION)
        self.assertEqual(
            self.activity_service.events[0]["details"]["items"][1][
                "unit_abbreviation"
            ],
            "sack",
        )
        self.assertEqual(self.expense_repository.rows, [])

    async def test_non_poultry_purchase_is_recorded_as_linked_expense(self):
        self.products[self.product_ids[1]].product_type = ProductType.FEED
        purchase_request = self._purchase_data(
            [
                PaymentCreate(
                    amount=Decimal("20000.00"),
                    payment_date=date(2026, 10, 9),
                    payment_method="cash",
                )
            ]
        )
        purchase_request.items[1].chicken_type = None

        purchase = await self.service.create_transaction(
            self.farm_id,
            purchase_request,
        )

        self.assertEqual(len(self.expense_repository.rows), 1)
        expense = self.expense_repository.rows[0]
        self.assertEqual(expense.name, "Product 2")
        self.assertEqual(expense.amount, Decimal("10000.00"))
        self.assertEqual(expense.category, "feed_and_nutrition")
        self.assertEqual(expense.purchase_transaction_id, purchase.id)
        self.assertEqual(len(expense.payments), 1)
        self.assertEqual(expense.payments[0].amount, Decimal("10000.00"))
        purchase_activity = next(
            event["details"]
            for event in self.activity_service.events
            if event["activity_type"] == ActivityType.EXPENSE_RECORDED
        )
        self.assertEqual(purchase_activity["product_names"], "Product 2")
        self.assertEqual(purchase_activity["expense_name"], "Product 2")
        self.assertEqual(
            expense.payments[0].purchase_payment_id,
            purchase.payments[0].id,
        )

    async def test_later_purchase_payment_updates_linked_expense_history(self):
        self.products[self.product_ids[1]].product_type = ProductType.FEED
        purchase_request = self._purchase_data()
        purchase_request.items[1].chicken_type = None
        purchase = await self.service.create_transaction(
            self.farm_id,
            purchase_request,
        )
        payment = SimpleNamespace(
            id=uuid4(),
            amount=Decimal("1250.00"),
            payment_date=date(2026, 10, 10),
            payment_method=PaymentMethod.CASH,
            reference_number=None,
        )

        await self.service._sync_purchase_expense_payment(
            SimpleNamespace(
                id=purchase.id,
                transaction_type=TransactionType.PURCHASE,
            ),
            payment,
        )

        expense = self.expense_repository.rows[0]
        self.assertEqual(len(expense.payments), 1)
        self.assertEqual(expense.payments[0].amount, payment.amount)
        self.assertEqual(expense.payments[0].purchase_payment_id, payment.id)

    async def test_fixed_discount_reduces_total_and_is_allocated_to_item_totals(self):
        transaction_data = self._purchase_data().model_copy(
            update={
                "discount_type": "fixed",
                "discount_value": Decimal("20000.00"),
                "discount_reason": "Supplier negotiation",
            }
        )

        purchase = await self.service.create_transaction(
            self.farm_id,
            transaction_data,
        )

        self.assertEqual(purchase.transaction_total, Decimal("50000.00"))
        self.assertEqual(purchase.discount_type, "fixed")
        self.assertEqual(purchase.discount_value, Decimal("20000.00"))
        self.assertEqual(purchase.discount_amount, Decimal("20000.00"))
        self.assertEqual(purchase.discount_reason, "Supplier negotiation")
        self.assertEqual(
            [item.subtotal_amount for item in purchase.items],
            [Decimal("60000.00"), Decimal("10000.00")],
        )
        self.assertEqual(
            [item.discount_amount for item in purchase.items],
            [Decimal("17142.86"), Decimal("2857.14")],
        )
        self.assertEqual(
            [item.total_amount for item in purchase.items],
            [Decimal("42857.14"), Decimal("7142.86")],
        )

    async def test_purchase_without_initial_payment_has_full_balance(self):
        purchase = await self.service.create_transaction(
            self.farm_id,
            self._purchase_data(),
        )

        self.assertEqual(purchase.amount_paid, Decimal("0.00"))
        self.assertEqual(purchase.balance_due, purchase.transaction_total)
        self.assertEqual(purchase.credit_balance, Decimal("0.00"))
        self.assertEqual(purchase.payments, [])

    async def test_reference_counter_restarts_for_each_date_and_type(self):
        first_purchase = await self.service.create_transaction(
            self.farm_id,
            self._purchase_data(),
        )
        second_purchase = await self.service.create_transaction(
            self.farm_id,
            self._purchase_data(),
        )
        next_date_purchase = await self.service.create_transaction(
            self.farm_id,
            self._purchase_data(transaction_date=date(2026, 10, 10)),
        )
        sale = await self.service.create_transaction(
            self.farm_id,
            TransactionCreate(
                transaction_type=TransactionType.SALE,
                transaction_date=date(2026, 10, 9),
                items=[
                    {
                        "product_id": self.product_ids[0],
                        "chicken_type": ChickenType.LAYERS,
                        "unit_id": self.unit_ids[0],
                        "quantity": 1,
                        "unit_price": Decimal("150.00"),
                    }
                ],
            ),
        )

        self.assertEqual(first_purchase.reference_number, "PUR-20261009-0001")
        self.assertEqual(second_purchase.reference_number, "PUR-20261009-0002")
        self.assertEqual(next_date_purchase.reference_number, "PUR-20261010-0001")
        self.assertEqual(sale.reference_number, "SAL-20261009-0001")

    def test_farm_local_date_uses_configured_timezone(self):
        self.assertEqual(
            farm_local_date(
                "Pacific/Kiritimati",
                datetime(2026, 10, 11, 23, 30, tzinfo=UTC),
            ),
            date(2026, 10, 12),
        )

    async def test_missing_transaction_date_uses_farm_local_date(self):
        transaction_data = self._purchase_data().model_copy(
            update={"transaction_date": None}
        )
        farm_date = date(2026, 10, 12)
        with patch(
            "app.services.transaction_service.farm_local_date",
            return_value=farm_date,
        ) as get_farm_date:
            purchase = await self.service.create_transaction(
                self.farm_id,
                transaction_data,
            )

        get_farm_date.assert_called_once_with("Pacific/Kiritimati")
        self.assertEqual(purchase.transaction_date, farm_date)
        self.assertEqual(purchase.reference_number, "PUR-20261012-0001")

    async def test_invalid_supplier_contact_is_rejected(self):
        self.contact_repository.contact = None
        with self.assertRaises(ResourceNotFoundError):
            await self.service.create_transaction(
                self.farm_id,
                self._purchase_data(),
            )

    async def test_products_not_sellable_remain_available_for_purchase(self):
        self.products[self.product_ids[0]].is_sellable = False

        purchase = await self.service.create_transaction(
            self.farm_id,
            self._purchase_data(),
        )

        self.assertEqual(purchase.transaction_type, TransactionType.PURCHASE)

    async def test_products_not_sellable_are_rejected_for_sale(self):
        self.products[self.product_ids[0]].is_sellable = False
        sale_data = TransactionCreate(
            transaction_type=TransactionType.SALE,
            transaction_date=date(2026, 10, 9),
            items=[
                {
                    "product_id": self.product_ids[0],
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": self.unit_ids[0],
                    "quantity": 1,
                    "unit_price": Decimal("150.00"),
                }
            ],
        )

        with self.assertRaisesRegex(ConflictError, "not marked as available for sale"):
            await self.service.create_transaction(self.farm_id, sale_data)

    async def test_invalid_unit_is_rejected(self):
        self.product_units.clear()
        with self.assertRaises(ConflictError):
            await self.service.create_transaction(
                self.farm_id,
                self._purchase_data(),
            )

    async def test_missing_product_is_rejected(self):
        self.products.pop(self.product_ids[0])
        with self.assertRaises(ResourceNotFoundError):
            await self.service.create_transaction(
                self.farm_id,
                self._purchase_data(),
            )

    async def test_fractional_chicken_conversion_is_rejected(self):
        self.product_units[(self.product_ids[0], self.unit_ids[0])].conversion_factor = (
            Decimal("0.5")
        )
        purchase_data = TransactionCreate(
            transaction_type=TransactionType.PURCHASE,
            transaction_date=date(2026, 10, 9),
            items=[
                {
                    "product_id": self.product_ids[0],
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": self.unit_ids[0],
                    "quantity": 1,
                    "unit_price": Decimal("100"),
                }
            ],
        )

        with self.assertRaises(ConflictError):
            await self.service.create_transaction(self.farm_id, purchase_data)

    async def test_chicken_purchase_service_builds_purchase_for_multiple_items(self):
        class CapturingTransactionService:
            async def create_transaction(inner_self, farm_id, transaction_data, user_id=None):
                inner_self.data = transaction_data
                inner_self.user_id = user_id
                return SimpleNamespace(
                    id=uuid4(),
                    transaction_date=transaction_data.transaction_date,
                    items=[
                        SimpleNamespace(
                            id=uuid4(),
                            ordered_base_quantity=Decimal(str(item.quantity)),
                        )
                        for item in transaction_data.items
                    ],
                )

        transaction_service = CapturingTransactionService()
        purchase_service = ChickenPurchaseService(
            product_repository=FakeProductRepository(self.products),
            transaction_service=transaction_service,
        )
        request = ChickenPurchaseRequest(
            transaction_date=date(2026, 10, 9),
            supplier_id=self.supplier_id,
            discount_type="percentage",
            discount_value=Decimal("10.00"),
            items=[
                {
                    "product_id": self.product_ids[0],
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": self.unit_ids[0],
                    "quantity": 4,
                    "unit_price": "150.00",
                },
                {
                    "product_id": self.product_ids[1],
                    "chicken_type": ChickenType.BROILER,
                    "unit_id": self.unit_ids[1],
                    "quantity": 2,
                    "unit_price": "2500.00",
                },
            ],
        )

        await purchase_service.create_chicken_purchase(self.farm_id, request)

        self.assertEqual(transaction_service.data.transaction_type, TransactionType.PURCHASE)
        self.assertEqual(len(transaction_service.data.items), 2)
        self.assertFalse(hasattr(transaction_service.data.items[0], "conversion_factor"))
        self.assertEqual(transaction_service.data.discount_type, "percentage")
        self.assertEqual(transaction_service.data.discount_value, Decimal("10.00"))

    async def test_chicken_purchase_requires_confirmation_for_discounted_overpayment(self):
        class CapturingTransactionService:
            async def create_transaction(inner_self, farm_id, transaction_data, user_id=None):
                inner_self.data = transaction_data
                return transaction_data

        async def create_purchase(confirmed):
            transaction_service = CapturingTransactionService()
            purchase_service = ChickenPurchaseService(
                product_repository=FakeProductRepository(self.products),
                transaction_service=transaction_service,
            )
            request = ChickenPurchaseRequest(
                transaction_date=date(2026, 10, 9),
                discount_type="fixed",
                discount_value=Decimal("100.00"),
                overpayment_confirmed=confirmed,
                items=[
                    {
                        "product_id": self.product_ids[0],
                        "chicken_type": ChickenType.LAYERS,
                        "unit_id": self.unit_ids[0],
                        "quantity": 4,
                        "unit_price": "150.00",
                    }
                ],
                payments=[
                    {
                        "amount": "600.00",
                        "payment_date": "2026-10-09",
                        "payment_method": "cash",
                    }
                ],
            )
            result = await purchase_service.create_chicken_purchase(
                self.farm_id,
                request,
            )
            return transaction_service, result

        with self.assertRaisesRegex(ConflictError, "Confirm the overpayment"):
            await create_purchase(False)

        transaction_service, _ = await create_purchase(True)
        self.assertEqual(transaction_service.data.discount_value, Decimal("100.00"))

    async def test_chicken_purchase_rejects_non_chicken_product(self):
        product_id = self.product_ids[0]
        self.products[product_id].product_type = ProductType.FEED
        purchase_service = ChickenPurchaseService(
            product_repository=FakeProductRepository(self.products),
            transaction_service=SimpleNamespace(),
        )
        request = ChickenPurchaseRequest(
            transaction_date=date(2026, 10, 9),
            items=[
                {
                    "product_id": product_id,
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": self.unit_ids[0],
                    "quantity": 1,
                    "unit_price": "1.00",
                }
            ],
        )

        with self.assertRaises(ConflictError):
            await purchase_service.create_chicken_purchase(self.farm_id, request)

    async def test_additional_payment_updates_balance_not_purchase_total(self):
        transaction_id = uuid4()
        transaction = SimpleNamespace(
            id=transaction_id,
            farm_id=self.farm_id,
            contact_id=None,
            reference_number=None,
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            items=[SimpleNamespace(total_amount=Decimal("70000.00"))],
        )
        existing_payment = SimpleNamespace(
            id=uuid4(),
            transaction_id=transaction_id,
            amount=Decimal("20000.00"),
        )
        payment_repository = FakePaymentRepository([existing_payment])
        transaction_service = TransactionService(
            transaction_repository=FakeTransactionRepository(transaction),
            transaction_item_repository=FakeTransactionItemRepository(),
            transaction_payment_repository=payment_repository,
            contact_repository=self.contact_repository,
            product_repository=FakeProductRepository(self.products),
            product_unit_repository=FakeProductUnitRepository(self.product_units),
            unit_of_work=FakeUnitOfWork(),
            activity_service=self.activity_service,
            sale_return_repository=FakeCreditRepository(),
            transaction_refund_repository=FakeRefundRepository(),
        )

        result = await transaction_service.record_payment(
            self.farm_id,
            transaction_id,
            PaymentCreate(
                amount=Decimal("5000.00"),
                payment_date=date(2026, 10, 10),
                payment_time=time(14, 30),
                payment_method="mpesa",
            ),
        )

        self.assertEqual(result.payment.amount, Decimal("5000.00"))
        self.assertEqual(result.payment.payment_time, time(14, 30))
        self.assertEqual(result.amount_paid, Decimal("25000.00"))
        self.assertEqual(result.balance_due, Decimal("45000.00"))
        self.assertEqual(result.credit_balance, Decimal("0.00"))
        self.assertEqual(transaction.items[0].total_amount, Decimal("70000.00"))
        self.assertEqual(
            self.activity_service.events[-1]["activity_type"],
            ActivityType.TRANSACTION_PAYMENT_RECORDED,
        )
        self.assertEqual(
            self.activity_service.events[-1]["entity_id"],
            result.payment.id,
        )

    async def test_additional_payment_accepts_sale_transaction(self):
        transaction = SimpleNamespace(
            id=uuid4(),
            farm_id=self.farm_id,
            contact_id=None,
            reference_number=None,
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            items=[SimpleNamespace(total_amount=Decimal("100.00"))],
        )
        transaction_service = TransactionService(
            transaction_repository=FakeTransactionRepository(transaction),
            transaction_item_repository=FakeTransactionItemRepository(),
            transaction_payment_repository=FakePaymentRepository(),
            contact_repository=self.contact_repository,
            product_repository=FakeProductRepository(self.products),
            product_unit_repository=FakeProductUnitRepository(self.product_units),
            unit_of_work=FakeUnitOfWork(),
            activity_service=self.activity_service,
            sale_return_repository=FakeCreditRepository(),
            transaction_refund_repository=FakeRefundRepository(),
        )

        result = await transaction_service.record_payment(
            self.farm_id,
            transaction.id,
            PaymentCreate(
                amount=Decimal("50.00"),
                payment_date=date(2026, 10, 10),
                payment_method="cash",
            ),
        )

        self.assertEqual(result.amount_paid, Decimal("50.00"))
        self.assertEqual(result.balance_due, Decimal("50.00"))
        self.assertEqual(result.credit_balance, Decimal("0.00"))

    async def test_overpayment_is_reported_as_credit_balance(self):
        transaction_id = uuid4()
        transaction = SimpleNamespace(
            id=transaction_id,
            farm_id=self.farm_id,
            contact_id=None,
            reference_number=None,
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            items=[SimpleNamespace(total_amount=Decimal("70000.00"))],
        )
        payment_repository = FakePaymentRepository(
            [
                SimpleNamespace(
                    id=uuid4(),
                    transaction_id=transaction_id,
                    amount=Decimal("70000.00"),
                )
            ]
        )
        transaction_service = TransactionService(
            transaction_repository=FakeTransactionRepository(transaction),
            transaction_item_repository=FakeTransactionItemRepository(),
            transaction_payment_repository=payment_repository,
            contact_repository=self.contact_repository,
            product_repository=FakeProductRepository(self.products),
            product_unit_repository=FakeProductUnitRepository(self.product_units),
            unit_of_work=FakeUnitOfWork(),
            activity_service=self.activity_service,
            sale_return_repository=FakeCreditRepository(),
            transaction_refund_repository=FakeRefundRepository(),
        )

        result = await transaction_service.record_payment(
            self.farm_id,
            transaction_id,
            PaymentCreate(
                amount=Decimal("5000.00"),
                payment_date=date(2026, 10, 10),
                payment_method="mpesa",
            ),
        )

        self.assertEqual(result.amount_paid, Decimal("75000.00"))
        self.assertEqual(result.balance_due, Decimal("0.00"))
        self.assertEqual(result.credit_balance, Decimal("5000.00"))

    async def test_payment_summary_uses_existing_credits_and_refunds(self):
        transaction_id = uuid4()
        transaction = SimpleNamespace(
            id=transaction_id,
            farm_id=self.farm_id,
            contact_id=None,
            reference_number=None,
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            items=[SimpleNamespace(total_amount=Decimal("100.00"))],
        )
        transaction_service = TransactionService(
            transaction_repository=FakeTransactionRepository(transaction),
            transaction_item_repository=FakeTransactionItemRepository(),
            transaction_payment_repository=FakePaymentRepository(
                [
                    SimpleNamespace(
                        id=uuid4(),
                        transaction_id=transaction_id,
                        amount=Decimal("100.00"),
                    )
                ]
            ),
            contact_repository=self.contact_repository,
            product_repository=FakeProductRepository(self.products),
            product_unit_repository=FakeProductUnitRepository(self.product_units),
            unit_of_work=FakeUnitOfWork(),
            activity_service=self.activity_service,
            sale_return_repository=FakeCreditRepository(Decimal("30.00")),
            transaction_refund_repository=FakeRefundRepository(Decimal("20.00")),
        )

        result = await transaction_service.record_payment(
            self.farm_id,
            transaction_id,
            PaymentCreate(
                amount=Decimal("5.00"),
                payment_date=date(2026, 10, 10),
                payment_method="cash",
            ),
        )

        self.assertEqual(result.amount_paid, Decimal("85.00"))
        self.assertEqual(result.balance_due, Decimal("0.00"))
        self.assertEqual(result.credit_balance, Decimal("15.00"))

    async def test_purchase_payment_summary_uses_supplier_cash_refunds(self):
        transaction_id = uuid4()
        transaction = SimpleNamespace(
            id=transaction_id,
            farm_id=self.farm_id,
            contact_id=None,
            reference_number=None,
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            items=[SimpleNamespace(total_amount=Decimal("100.00"))],
        )
        transaction_service = TransactionService(
            transaction_repository=FakeTransactionRepository(transaction),
            transaction_item_repository=FakeTransactionItemRepository(),
            transaction_payment_repository=FakePaymentRepository(
                [
                    SimpleNamespace(
                        id=uuid4(),
                        transaction_id=transaction_id,
                        amount=Decimal("100.00"),
                    )
                ]
            ),
            contact_repository=self.contact_repository,
            product_repository=FakeProductRepository(self.products),
            product_unit_repository=FakeProductUnitRepository(self.product_units),
            unit_of_work=FakeUnitOfWork(),
            activity_service=self.activity_service,
            sale_return_repository=FakeCreditRepository(),
            transaction_refund_repository=FakeRefundRepository(),
            purchase_supplier_refund_repository=FakeRefundRepository(
                Decimal("20.00")
            ),
        )

        result = await transaction_service.record_payment(
            self.farm_id,
            transaction_id,
            PaymentCreate(
                amount=Decimal("5.00"),
                payment_date=date(2026, 10, 10),
                payment_method="cash",
            ),
        )

        self.assertEqual(result.amount_paid, Decimal("85.00"))
        self.assertEqual(result.balance_due, Decimal("15.00"))
        self.assertEqual(result.credit_balance, Decimal("0.00"))

    async def test_sale_transaction_accepts_customer_and_credit_balance(self):
        customer_id = uuid4()
        self.contact_repository.contact = SimpleNamespace(
            id=customer_id,
            name="Farm customer",
            contact_roles=[SimpleNamespace(role=ContactRoleEnum.CUSTOMER)],
        )
        sale_data = TransactionCreate(
            transaction_type=TransactionType.SALE,
            transaction_date=date(2026, 10, 9),
            contact_id=customer_id,
            discount_type="fixed",
            discount_value=Decimal("100.00"),
            discount_reason="Bulk sale",
            items=[
                {
                    "product_id": self.product_ids[0],
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": self.unit_ids[0],
                    "quantity": 10,
                    "unit_price": Decimal("200.00"),
                }
            ],
            payments=[
                PaymentCreate(
                    amount=Decimal("500.00"),
                    payment_date=date(2026, 10, 9),
                    payment_method="cash",
                )
            ],
        )

        sale = await self.service.create_transaction(self.farm_id, sale_data)

        self.assertEqual(sale.transaction_type, TransactionType.SALE)
        self.assertEqual(sale.transaction_total, Decimal("1900.00"))
        self.assertEqual(sale.discount_amount, Decimal("100.00"))
        self.assertEqual(sale.discount_reason, "Bulk sale")
        self.assertEqual(sale.amount_paid, Decimal("500.00"))
        self.assertEqual(sale.balance_due, Decimal("1400.00"))
        self.assertEqual(sale.credit_balance, Decimal("0.00"))

    async def test_chicken_sale_service_builds_sale_for_multi_batch_block_request(self):
        class CapturingTransactionService:
            async def create_transaction(
                inner_self,
                farm_id,
                transaction_data,
                user_id=None,
                *,
                commit=True,
            ):
                inner_self.data = transaction_data
                inner_self.user_id = user_id
                return SimpleNamespace(
                    id=uuid4(),
                    transaction_date=transaction_data.transaction_date,
                    items=[
                        SimpleNamespace(
                            id=uuid4(),
                            ordered_base_quantity=Decimal(str(item.quantity)),
                        )
                        for item in transaction_data.items
                    ],
                )

        transaction_service = CapturingTransactionService()
        class CapturingSaleDeliveryService:
            async def create_delivery(
                inner_self,
                farm_id,
                transaction_id,
                request,
                user_id=None,
                *,
                commit=True,
            ):
                inner_self.request = request

        class FakeUnitOfWork:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                return False

            async def commit(self):
                pass

        sale_service = __import__("app.services.chicken_sale_service", fromlist=["ChickenSaleService"]).ChickenSaleService(
            product_repository=FakeProductRepository(self.products),
            transaction_service=transaction_service,
            sale_delivery_service=CapturingSaleDeliveryService(),
            unit_of_work=FakeUnitOfWork(),
        )
        request = ChickenSaleRequest(
            transaction_date=date(2026, 10, 9),
            customer_id=self.supplier_id,
            items=[
                {
                    "product_id": self.product_ids[0],
                    "chicken_type": ChickenType.LAYERS,
                    "unit_id": self.unit_ids[0],
                    "quantity": 12,
                    "unit_price": "150.00",
                    "batch_allocations": [
                        {"batch_id": str(uuid4()), "block_id": str(uuid4()), "quantity": 7},
                        {"batch_id": str(uuid4()), "block_id": str(uuid4()), "quantity": 5},
                    ],
                }
            ],
        )

        await sale_service.create_chicken_sale(self.farm_id, request)

        self.assertEqual(transaction_service.data.transaction_type, TransactionType.SALE)
        self.assertEqual(len(transaction_service.data.items), 1)
        self.assertEqual(len(transaction_service.data.items[0].batch_allocations), 2)


if __name__ == "__main__":
    unittest.main()

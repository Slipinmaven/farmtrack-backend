import unittest
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.models.farm import Farm
from app.schemas.egg_sale import EggSaleCreateRequest
from app.schemas.enums import InventoryMovementType, ProductType, TransactionType
from app.services.egg_sale_service import EggSaleService


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


class FakeTotalsRepository:
    def __init__(self, totals):
        self.totals = totals

    async def get_totals_by_farm(self, farm_id):
        return self.totals


class FakeTransactionItemRepository:
    def __init__(self, totals):
        self.totals = totals

    async def get_sold_base_quantities_by_farm(self, farm_id):
        return self.totals


class FakeInventoryMovementRepository:
    def __init__(self):
        self.totals = {}

    async def get_totals_by_type(self, farm_id, movement_type):
        return self.totals.get(movement_type, {})


class FakeTransactionService:
    def __init__(self):
        self.calls = []
        self.response = SimpleNamespace(id=uuid4())

    async def create_transaction(self, farm_id, data, user_id, *, commit):
        self.calls.append((farm_id, data, user_id, commit))
        return self.response


class EggSaleServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.farm = cast(
            Farm,
            SimpleNamespace(id=self.farm_id, owner_id=uuid4()),
        )
        self.product_id = uuid4()
        self.dozen_unit_id = uuid4()
        self.piece_unit_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            farm_id=self.farm_id,
            name="Table eggs",
            product_type=ProductType.EGGS,
            is_active=True,
            is_sellable=True,
        )
        products = {self.product_id: self.product}
        units = {
            (self.product_id, self.dozen_unit_id): SimpleNamespace(
                conversion_factor=Decimal("12.000")
            ),
            (self.product_id, self.piece_unit_id): SimpleNamespace(
                conversion_factor=Decimal("1.000")
            ),
        }
        self.product_repository = FakeProductRepository(products)
        self.transaction_item_repository = FakeTransactionItemRepository({})
        self.inventory_movement_repository = FakeInventoryMovementRepository()
        self.transaction_service = FakeTransactionService()
        self.unit_of_work = FakeUnitOfWork()
        self.service = EggSaleService(
            product_repository=cast(Any, self.product_repository),
            product_unit_repository=cast(Any, FakeProductUnitRepository(units)),
            collection_repository=cast(
                Any,
                FakeTotalsRepository({self.product_id: Decimal("100.000")}),
            ),
            loss_repository=cast(Any, FakeTotalsRepository({})),
            inventory_movement_repository=cast(
                Any,
                self.inventory_movement_repository,
            ),
            transaction_item_repository=cast(
                Any,
                self.transaction_item_repository,
            ),
            transaction_service=cast(Any, self.transaction_service),
            unit_of_work=cast(Any, self.unit_of_work),
        )

    def _request(self, items=None, **overrides):
        data = {
            "items": items
            or [
                {
                    "product_id": str(self.product_id),
                    "unit_id": str(self.dozen_unit_id),
                    "quantity": "2",
                    "unit_price": "4.50",
                },
                {
                    "product_id": str(self.product_id),
                    "unit_id": str(self.piece_unit_id),
                    "quantity": "5",
                    "unit_price": "0.40",
                },
            ]
        }
        data.update(overrides)
        return EggSaleCreateRequest.model_validate(data)

    async def test_mixed_units_create_one_atomic_sale_transaction(self):
        result = await self.service.create_sale(self.farm, self._request())

        self.assertIs(result, self.transaction_service.response)
        self.assertEqual(self.product_repository.locked_ids, [self.product_id])
        self.assertEqual(self.unit_of_work.commit_count, 1)
        self.assertEqual(len(self.transaction_service.calls), 1)
        farm_id, transaction, user_id, commit = self.transaction_service.calls[0]
        self.assertEqual(farm_id, self.farm_id)
        self.assertEqual(user_id, self.farm.owner_id)
        self.assertFalse(commit)
        self.assertEqual(transaction.transaction_type, TransactionType.SALE)
        self.assertTrue(transaction.fulfillment_required)
        self.assertEqual(len(transaction.items), 2)

    async def test_split_payments_and_overpayment_are_passed_to_sale_transaction(self):
        result = await self.service.create_sale(
            self.farm,
            self._request(
                payments=[
                    {
                        "amount": "7.00",
                        "payment_date": "2026-10-10",
                        "payment_method": "bank_transfer",
                        "reference_number": "BANK-123",
                    },
                    {
                        "amount": "7.00",
                        "payment_date": "2026-10-10",
                        "payment_method": "cash",
                    },
                ]
            ),
        )

        self.assertIs(result, self.transaction_service.response)
        payments = self.transaction_service.calls[0][1].payments
        self.assertEqual(len(payments), 2)
        self.assertEqual(
            [payment.payment_method.value for payment in payments],
            ["bank_transfer", "cash"],
        )
        self.assertEqual(payments[0].reference_number, "BANK-123")

    async def test_underpayment_is_accepted_as_a_sale_balance(self):
        await self.service.create_sale(
            self.farm,
            self._request(
                payments=[
                    {
                        "amount": "3.00",
                        "payment_date": "2026-10-10",
                        "payment_method": "cash",
                    }
                ]
            ),
        )

        self.assertEqual(
            self.transaction_service.calls[0][1].payments[0].amount,
            Decimal("3.00"),
        )

    async def test_combined_quantities_cannot_exceed_remaining_stock(self):
        with self.assertRaises(ConflictError):
            await self.service.create_sale(
                self.farm,
                self._request(
                    items=[
                        {
                            "product_id": str(self.product_id),
                            "unit_id": str(self.dozen_unit_id),
                            "quantity": "8",
                            "unit_price": "4.50",
                        },
                        {
                            "product_id": str(self.product_id),
                            "unit_id": str(self.piece_unit_id),
                            "quantity": "5",
                            "unit_price": "0.40",
                        },
                    ]
                ),
            )

        self.assertEqual(self.transaction_service.calls, [])
        self.assertEqual(self.unit_of_work.commit_count, 0)

    async def test_previous_sales_are_subtracted_from_available_stock(self):
        self.transaction_item_repository.totals[self.product_id] = Decimal("98.000")

        with self.assertRaises(ConflictError):
            await self.service.create_sale(
                self.farm,
                self._request(
                    items=[
                        {
                            "product_id": str(self.product_id),
                            "unit_id": str(self.piece_unit_id),
                            "quantity": "3",
                            "unit_price": "0.40",
                        }
                    ]
                ),
            )

        self.assertEqual(self.transaction_service.calls, [])

    async def test_settlement_issued_eggs_are_subtracted_from_available_stock(self):
        self.inventory_movement_repository.totals[
            InventoryMovementType.SETTLEMENT_ISSUED
        ] = {self.product_id: Decimal("-80.000")}

        with self.assertRaises(ConflictError):
            await self.service.create_sale(
                self.farm,
                self._request(
                    items=[
                        {
                            "product_id": str(self.product_id),
                            "unit_id": str(self.piece_unit_id),
                            "quantity": "21",
                            "unit_price": "0.40",
                        }
                    ]
                ),
            )

        self.assertEqual(self.transaction_service.calls, [])
        self.assertEqual(self.unit_of_work.commit_count, 0)

    async def test_settlement_received_eggs_increase_available_stock(self):
        self.inventory_movement_repository.totals[
            InventoryMovementType.SETTLEMENT_RECEIVED
        ] = {self.product_id: Decimal("30.000")}

        await self.service.create_sale(
            self.farm,
            self._request(
                items=[
                    {
                        "product_id": str(self.product_id),
                        "unit_id": str(self.piece_unit_id),
                        "quantity": "120",
                        "unit_price": "0.40",
                    }
                ]
            ),
        )

        self.assertEqual(len(self.transaction_service.calls), 1)

    async def test_rejects_products_not_sellable_or_not_eggs(self):
        self.product.is_sellable = False
        with self.assertRaises(ConflictError):
            await self.service.create_sale(self.farm, self._request())

        self.product.is_sellable = True
        self.product.product_type = ProductType.FEED
        with self.assertRaises(ConflictError):
            await self.service.create_sale(self.farm, self._request())

        self.assertEqual(self.transaction_service.calls, [])

    async def test_rejects_product_outside_farm(self):
        self.product.farm_id = uuid4()

        with self.assertRaises(ResourceNotFoundError):
            await self.service.create_sale(self.farm, self._request())

        self.assertEqual(self.transaction_service.calls, [])

    def test_request_rejects_empty_items_and_invalid_quantity(self):
        with self.assertRaises(ValidationError):
            EggSaleCreateRequest.model_validate({"items": []})

        with self.assertRaises(ValidationError):
            self._request(
                items=[
                    {
                        "product_id": str(self.product_id),
                        "unit_id": str(self.piece_unit_id),
                        "quantity": "0",
                        "unit_price": "0.40",
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.core.exceptions import ConflictError
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    ChickenType,
    ContactRoleEnum,
    PaymentMethod,
    ProductType,
    SaleReturnType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.sale_return import SaleReturnCreateRequest
from app.schemas.transaction_refund import TransactionRefundCreateRequest
from app.services.sale_return_service import SaleReturnService
from app.services.transaction_refund_service import TransactionRefundService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def commit(self):
        pass


class FakeTransactionRepository:
    def __init__(self, transaction):
        self.transaction = transaction

    async def get_by_id_for_update(self, farm_id, transaction_id):
        return self.transaction if self.transaction.id == transaction_id else None

    async def get_by_id(self, farm_id, transaction_id):
        return self.transaction if self.transaction.id == transaction_id else None


class FakeContactRepository:
    def __init__(self, contact):
        self.contact = contact

    async def get_by_id(self, farm_id, contact_id):
        if self.contact is None or self.contact.id != contact_id:
            return None
        return self.contact


class FakeProductRepository:
    def __init__(self, product):
        self.product = product

    async def get_by_id(self, farm_id, product_id):
        if product_id == self.product.id and farm_id == self.product.farm_id:
            return self.product
        return None


class FakeDeliveryRepository:
    def __init__(self, transaction_item_id, batch_id, delivered_quantity):
        self.transaction_item_id = transaction_item_id
        self.batch_id = batch_id
        self.delivered_quantity = delivered_quantity

    async def get_delivered_quantities_by_transaction(self, transaction_id):
        return {self.transaction_item_id: Decimal(self.delivered_quantity)}

    async def get_delivered_quantities_by_batch(self, transaction_id):
        return {(self.transaction_item_id, self.batch_id): self.delivered_quantity}


class FakeReturnRepository:
    def __init__(self):
        self.returns = []
        self.items = []
        self.allocations = []

    async def get_quantities_by_type(self, transaction_id, return_type):
        totals = {}
        for sale_return in self.returns:
            if sale_return.return_type != return_type:
                continue
            for item in sale_return.items:
                totals[item.transaction_item_id] = (
                    totals.get(item.transaction_item_id, Decimal("0")) + item.quantity
                )
        return totals

    async def list_by_transaction(self, transaction_id):
        return self.returns

    async def get_credited_quantities_by_item(self, transaction_id):
        totals = {}
        for item in self.items:
            totals[item.transaction_item_id] = (
                totals.get(item.transaction_item_id, Decimal("0")) + item.quantity
            )
        return totals

    async def get_credit_amounts_by_item(self, transaction_id):
        totals = {}
        for item in self.items:
            totals[item.transaction_item_id] = (
                totals.get(item.transaction_item_id, Decimal("0.00"))
                + item.credit_amount
            )
        return totals

    async def get_total_credit_by_transaction(self, transaction_id):
        return sum(
            (item.credit_amount for item in self.items),
            Decimal("0.00"),
        )

    async def get_returned_quantities_by_batch(self, transaction_id):
        totals = {}
        for allocation in self.allocations:
            sale_return = next(
                record
                for record in self.returns
                if record.id == allocation.sale_return_id
            )
            if sale_return.return_type != SaleReturnType.DELIVERED_RETURN.value:
                continue
            item = next(
                record
                for record in self.items
                if record.id == allocation.sale_return_item_id
            )
            key = (item.transaction_item_id, allocation.batch_id)
            totals[key] = totals.get(key, 0) + allocation.quantity
        return totals

    async def create_return(self, data):
        sale_return = SimpleNamespace(
            id=uuid4(),
            created_at=datetime.now(),
            items=[],
            **data,
        )
        self.returns.append(sale_return)
        return sale_return

    async def create_item(self, data):
        item = SimpleNamespace(id=uuid4(), batch_allocations=[], **data)
        sale_return = next(
            record
            for record in self.returns
            if record.id == data["sale_return_id"]
        )
        sale_return.items.append(item)
        self.items.append(item)
        return item

    async def create_allocation(self, data):
        allocation = SimpleNamespace(id=uuid4(), **data)
        self.allocations.append(allocation)
        item = next(
            record
            for record in self.items
            if record.id == data["sale_return_item_id"]
        )
        item.batch_allocations.append(allocation)
        return allocation


class FakePaymentRepository:
    def __init__(self, payments):
        self.payments = payments

    async def list_by_transaction(self, transaction_id):
        return self.payments


class FakeRefundRepository:
    def __init__(self, total=Decimal("0.00")):
        self.refunds = []
        self.total = total

    async def get_total_by_transaction(self, transaction_id):
        return self.total + sum(
            (refund.amount for refund in self.refunds),
            Decimal("0.00"),
        )

    async def create(self, data):
        data.setdefault("refund_time", None)
        data.setdefault("reference_number", None)
        data.setdefault("notes", None)
        refund = SimpleNamespace(
            id=uuid4(),
            transaction_id=data["transaction_id"],
            created_at=datetime.now(),
            updated_at=datetime.now(),
            **{key: value for key, value in data.items() if key != "transaction_id"},
        )
        self.refunds.append(refund)
        return refund

    async def list_by_transaction(self, transaction_id):
        return self.refunds


class FakeBatchRepository:
    def __init__(self, batch):
        self.batch = batch

    async def get_by_id(self, farm_id, batch_id):
        if self.batch.id == batch_id and self.batch.farm_id == farm_id:
            return self.batch
        return None


class FakeBlockRepository:
    def __init__(self, block):
        self.block = block

    async def get_by_id_for_update(self, farm_id, block_id):
        if self.block.id == block_id and self.block.farm_id == farm_id:
            return self.block
        return None


class FakeBatchBlockRepository:
    def __init__(self, assignments):
        self.assignments = assignments

    async def get_total_quantity_by_block(self, block_id):
        return sum(
            assignment.quantity
            for (_, assignment_block_id), assignment in self.assignments.items()
            if assignment_block_id == block_id
        )

    async def get_by_batch_and_block(self, batch_id, block_id):
        return self.assignments.get((batch_id, block_id))

    async def create(self, data):
        assignment = SimpleNamespace(**data)
        self.assignments[(data["batch_id"], data["block_id"])] = assignment
        return assignment

    async def update(self, assignment):
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


class SaleReturnRefundServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.farm_id = uuid4()
        self.transaction_id = uuid4()
        self.customer_id = uuid4()
        self.transaction_item_id = uuid4()
        self.product_id = uuid4()
        self.batch_id = uuid4()
        self.block_id = uuid4()
        self.transaction = SimpleNamespace(
            id=self.transaction_id,
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            reference_number=None,
            contact_id=self.customer_id,
            items=[
                SimpleNamespace(
                    id=self.transaction_item_id,
                    product_id=self.product_id,
                    quantity=Decimal("10"),
                    conversion_factor=Decimal("1"),
                    total_amount=Decimal("100.00"),
                    chicken_type=ChickenType.LAYERS,
                )
            ],
        )
        product = SimpleNamespace(
            id=self.product_id,
            farm_id=self.farm_id,
            product_type=ProductType.CHICKENS,
        )
        batch = SimpleNamespace(
            id=self.batch_id,
            farm_id=self.farm_id,
            product_id=self.product_id,
            status=ChickenBatchStatus.ACTIVE,
            chicken_type=ChickenType.LAYERS,
            name="Layers",
        )
        block = SimpleNamespace(
            id=self.block_id,
            farm_id=self.farm_id,
            is_active=True,
            name="North",
            capacity=10,
            over_capacity_limit=0,
        )
        self.transaction_repository = FakeTransactionRepository(self.transaction)
        self.delivery_repository = FakeDeliveryRepository(
            self.transaction_item_id,
            self.batch_id,
            delivered_quantity=4,
        )
        self.return_repository = FakeReturnRepository()
        self.payment_repository = FakePaymentRepository(
            [SimpleNamespace(amount=Decimal("100.00"))]
        )
        self.refund_repository = FakeRefundRepository()
        self.batch_block = SimpleNamespace(
            batch_id=self.batch_id,
            block_id=self.block_id,
            quantity=6,
        )
        self.batch_block_repository = FakeBatchBlockRepository(
            {(self.batch_id, self.block_id): self.batch_block}
        )
        self.activity_service = FakeActivityService()
        self.inventory_service = FakeInventoryService()
        self.unit_of_work = FakeUnitOfWork()
        self.contact_repository = FakeContactRepository(
            SimpleNamespace(
                id=self.customer_id,
                name="Sale customer",
                contact_roles=[SimpleNamespace(role=ContactRoleEnum.CUSTOMER)],
            )
        )
        self.return_service = SaleReturnService(
            transaction_repository=self.transaction_repository,
            product_repository=FakeProductRepository(product),
            sale_delivery_repository=self.delivery_repository,
            sale_return_repository=self.return_repository,
            transaction_payment_repository=self.payment_repository,
            transaction_refund_repository=self.refund_repository,
            contact_repository=self.contact_repository,
            chicken_batch_repository=FakeBatchRepository(batch),
            block_repository=FakeBlockRepository(block),
            batch_block_repository=self.batch_block_repository,
            unit_of_work=self.unit_of_work,
            activity_service=self.activity_service,
            inventory_service=self.inventory_service,
        )
        self.refund_service = TransactionRefundService(
            transaction_repository=self.transaction_repository,
            transaction_payment_repository=self.payment_repository,
            transaction_refund_repository=self.refund_repository,
            sale_return_repository=self.return_repository,
            unit_of_work=self.unit_of_work,
            activity_service=self.activity_service,
        )

    def _return_request(self, return_type, quantity, allocations=None):
        return SaleReturnCreateRequest.model_validate(
            {
                "return_type": return_type.value,
                "return_date": date(2026, 10, 9),
                "reason": "Customer order adjustment",
                "items": [
                    {
                        "transaction_item_id": str(self.transaction_item_id),
                        "quantity": quantity,
                        "batch_allocations": allocations or [],
                    }
                ],
            }
        )

    def _refund_request(self, amount):
        return TransactionRefundCreateRequest.model_validate(
            {
                "amount": str(amount),
                "refund_date": date(2026, 10, 9),
                "payment_method": PaymentMethod.MPESA.value,
                "reason": "Sale credit refund",
            }
        )

    async def test_undelivered_cancellation_creates_credit_without_stock_change(self):
        result = await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 6),
        )

        self.assertEqual(result.credit_total, Decimal("60.00"))
        self.assertEqual(result.adjusted_transaction_total, Decimal("40.00"))
        self.assertEqual(result.amount_paid, Decimal("100.00"))
        self.assertEqual(result.credit_balance, Decimal("60.00"))
        self.assertEqual(self.batch_block.quantity, 6)
        self.assertEqual(self.return_repository.returns[0].return_type, "undelivered_cancelled")
        self.assertEqual(
            self.activity_service.events[-1]["activity_type"],
            ActivityType.SALE_RETURN_CREATED,
        )

    async def test_sale_return_credit_requires_linked_named_customer(self):
        self.transaction.contact_id = None

        with self.assertRaisesRegex(ConflictError, "customer with a name"):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 6),
            )

        self.assertEqual(self.return_repository.returns, [])

    async def test_cannot_cancel_more_than_undelivered_quantity(self):
        with self.assertRaises(ConflictError):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 7),
            )

    async def test_tracked_egg_return_cannot_exceed_delivered_quantity(self):
        self.transaction.fulfillment_required = True
        self.transaction.items[0].chicken_type = None
        self.return_service.product_repository.product.product_type = ProductType.EGGS

        with self.assertRaisesRegex(ConflictError, "only 4 were delivered"):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                self._return_request(SaleReturnType.DELIVERED_RETURN, 5),
            )

        self.assertEqual(self.return_repository.returns, [])
        self.assertEqual(self.inventory_service.movements, [])
        self.assertEqual(self.return_repository.returns, [])

    async def test_delivered_return_restocks_and_issues_proportional_credit(self):
        request = self._return_request(
            SaleReturnType.DELIVERED_RETURN,
            3,
            [
                {
                    "batch_id": str(self.batch_id),
                    "block_id": str(self.block_id),
                    "quantity": 3,
                }
            ],
        )
        result = await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            request,
        )

        self.assertEqual(result.credit_total, Decimal("30.00"))
        self.assertEqual(self.batch_block.quantity, 9)
        self.assertEqual(len(self.return_repository.allocations), 1)

        history = await self.return_service.list_returns(
            self.farm_id,
            self.transaction_id,
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].credit_total, Decimal("30.00"))
        self.assertEqual(history[0].items[0].batch_allocations[0].quantity, 3)
        self.assertEqual(
            self.inventory_service.movements[0]["quantity_delta"],
            Decimal("3"),
        )

    async def test_delivered_return_rejects_batch_linked_to_another_product(self):
        self.return_service.chicken_batch_repository.batch.product_id = uuid4()
        request = self._return_request(
            SaleReturnType.DELIVERED_RETURN,
            1,
            [
                {
                    "batch_id": str(self.batch_id),
                    "block_id": str(self.block_id),
                    "quantity": 1,
                }
            ],
        )

        with self.assertRaisesRegex(ConflictError, "not linked to the selected"):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                request,
            )

        self.assertEqual(self.batch_block.quantity, 6)
        self.assertEqual(self.return_repository.returns, [])
        self.assertEqual(self.inventory_service.movements, [])

    async def test_delivered_non_chicken_return_updates_shared_inventory(self):
        self.return_service.product_repository.product.product_type = ProductType.FEED
        request = self._return_request(
            SaleReturnType.DELIVERED_RETURN,
            Decimal("2.5"),
        )

        result = await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            request,
        )

        self.assertEqual(result.credit_total, Decimal("25.00"))
        self.assertEqual(
            self.inventory_service.movements[0]["quantity_delta"],
            Decimal("2.5"),
        )
        self.assertEqual(
            self.inventory_service.movements[0]["movement_type"].value,
            "customer_return",
        )

    async def test_delivered_return_cannot_exceed_recorded_deliveries(self):
        with self.assertRaises(ConflictError):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                self._return_request(
                    SaleReturnType.DELIVERED_RETURN,
                    5,
                    [
                        {
                            "batch_id": str(self.batch_id),
                            "block_id": str(self.block_id),
                            "quantity": 5,
                        }
                    ],
                ),
            )
        self.assertEqual(self.batch_block.quantity, 6)
        self.assertEqual(self.return_repository.returns, [])

    async def test_return_rejects_block_capacity_overflow_without_mutation(self):
        self.return_service.block_repository.block.capacity = 6
        with self.assertRaises(ConflictError):
            await self.return_service.create_return(
                self.farm_id,
                self.transaction_id,
                self._return_request(
                    SaleReturnType.DELIVERED_RETURN,
                    1,
                    [
                        {
                            "batch_id": str(self.batch_id),
                            "block_id": str(self.block_id),
                            "quantity": 1,
                        }
                    ],
                ),
            )
        self.assertEqual(self.batch_block.quantity, 6)
        self.assertEqual(self.return_repository.returns, [])

    async def test_refund_cannot_exceed_unrefunded_return_value(self):
        await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 6),
        )
        with self.assertRaises(ConflictError):
            await self.refund_service.create_refund(
                self.farm_id,
                self.transaction_id,
                self._refund_request("60.01"),
            )
        self.assertEqual(self.refund_repository.refunds, [])

    async def test_refund_uses_only_balance_owed_to_customer_after_return(self):
        self.payment_repository.payments = [
            SimpleNamespace(amount=Decimal("80.00"))
        ]
        await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 3),
        )

        result = await self.refund_service.create_refund(
            self.farm_id,
            self.transaction_id,
            self._refund_request("10.00"),
        )

        self.assertEqual(result.adjusted_transaction_total, Decimal("70.00"))
        self.assertEqual(result.amount_paid, Decimal("70.00"))
        self.assertEqual(result.balance_due, Decimal("0.00"))
        self.assertEqual(result.credit_balance, Decimal("0.00"))

    async def test_refund_is_not_allowed_when_sale_still_has_a_balance_due(self):
        self.payment_repository.payments = [
            SimpleNamespace(amount=Decimal("20.00"))
        ]
        await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 3),
        )

        with self.assertRaises(ConflictError):
            await self.refund_service.create_refund(
                self.farm_id,
                self.transaction_id,
                self._refund_request("0.01"),
            )

        self.assertEqual(self.refund_repository.refunds, [])

    async def test_discounted_return_uses_net_item_value_not_stored_credit(self):
        self.transaction.items[0].total_amount = Decimal("40.00")
        self.return_repository.items.append(
            SimpleNamespace(
                transaction_item_id=self.transaction_item_id,
                quantity=Decimal("4"),
                credit_amount=Decimal("24.00"),
            )
        )

        result = await self.refund_service.create_refund(
            self.farm_id,
            self.transaction_id,
            self._refund_request("16.00"),
        )

        self.assertEqual(result.adjusted_transaction_total, Decimal("24.00"))
        self.assertEqual(result.credit_balance, Decimal("60.00"))

    async def test_discounted_sale_return_recomputes_previous_return_credit(self):
        self.transaction.items[0].total_amount = Decimal("40.00")
        self.return_repository.items.append(
            SimpleNamespace(
                transaction_item_id=self.transaction_item_id,
                quantity=Decimal("4"),
                credit_amount=Decimal("24.00"),
            )
        )

        result = await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 6),
        )

        self.assertEqual(result.credit_total, Decimal("24.00"))
        self.assertEqual(result.adjusted_transaction_total, Decimal("0.00"))

    async def test_sale_return_history_recalculates_discounted_return_value(self):
        self.transaction.items[0].total_amount = Decimal("40.00")
        returned_item = SimpleNamespace(
            id=uuid4(),
            transaction_item_id=self.transaction_item_id,
            quantity=Decimal("4"),
            credit_amount=Decimal("24.00"),
            batch_allocations=[],
        )
        self.return_repository.returns.append(
            SimpleNamespace(
                id=uuid4(),
                transaction_id=self.transaction_id,
                return_type=SaleReturnType.DELIVERED_RETURN.value,
                return_date=date(2026, 10, 9),
                return_time=None,
                reason="Customer return",
                notes=None,
                created_at=datetime.now(),
                items=[returned_item],
            )
        )

        history = await self.return_service.list_returns(
            self.farm_id,
            self.transaction_id,
        )

        self.assertEqual(history[0].credit_total, Decimal("16.00"))
        self.assertEqual(history[0].items[0].credit_amount, Decimal("16.00"))

    async def test_refund_reduces_net_paid_and_customer_credit(self):
        await self.return_service.create_return(
            self.farm_id,
            self.transaction_id,
            self._return_request(SaleReturnType.UNDELIVERED_CANCELLED, 6),
        )
        result = await self.refund_service.create_refund(
            self.farm_id,
            self.transaction_id,
            self._refund_request("60.00"),
        )

        self.assertEqual(result.refund.amount, Decimal("60.00"))
        self.assertEqual(result.adjusted_transaction_total, Decimal("40.00"))
        self.assertEqual(result.amount_paid, Decimal("40.00"))
        self.assertEqual(result.balance_due, Decimal("0.00"))
        self.assertEqual(result.credit_balance, Decimal("0.00"))
        self.assertEqual(
            self.activity_service.events[-1]["entity_type"],
            ActivityEntityType.TRANSACTION_REFUND,
        )

    async def test_refund_is_not_allowed_for_purchase_transactions(self):
        self.transaction.transaction_type = TransactionType.PURCHASE

        with self.assertRaises(ConflictError):
            await self.refund_service.create_refund(
                self.farm_id,
                self.transaction_id,
                self._refund_request("1.00"),
            )

        self.assertEqual(self.refund_repository.refunds, [])


if __name__ == "__main__":
    unittest.main()

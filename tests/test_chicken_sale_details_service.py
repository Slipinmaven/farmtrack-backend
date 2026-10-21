import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.unit_of_work import UnitOfWork
from app.repositories.contact_repository import ContactRepository
from app.repositories.sale_delivery_repository import SaleDeliveryRepository
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import (
    ChickenType,
    PaymentMethod,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.services.chicken_sale_details_service import ChickenSaleDetailsService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        return False


class ChickenSaleDetailsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_details_include_allocations_payments_and_customer_balances(self):
        farm_id = uuid4()
        sale_id = uuid4()
        item_id = uuid4()
        customer_id = uuid4()
        now = datetime.now()
        payment = SimpleNamespace(
            id=uuid4(),
            transaction_id=sale_id,
            amount=Decimal("60.00"),
            payment_date=date(2026, 10, 1),
            payment_time=None,
            payment_method=PaymentMethod.CASH,
            reference_number="PAY-1",
            notes=None,
            created_at=now,
            updated_at=now,
        )
        item = SimpleNamespace(
            id=item_id,
            created_at=now,
            product_id=uuid4(),
            unit_id=uuid4(),
            product=SimpleNamespace(name="Broilers", product_type=ProductType.CHICKENS),
            unit=SimpleNamespace(name="each"),
            quantity=Decimal("2"),
            conversion_factor=Decimal("1"),
            chicken_type=ChickenType.BROILER,
            unit_price=Decimal("50.00"),
            subtotal_amount=Decimal("100.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
            notes=None,
        )
        sale = SimpleNamespace(
            id=sale_id,
            farm_id=farm_id,
            contact_id=customer_id,
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            transaction_date=date(2026, 10, 1),
            transaction_time=None,
            reference_number="SALE-001",
            notes="Delivered",
            discount_type=None,
            discount_value=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            discount_reason=None,
            items=[item],
            payments=[payment],
            created_at=now,
            updated_at=now,
        )
        other_sale = SimpleNamespace(
            id=uuid4(),
            transaction_type=TransactionType.SALE,
            status=TransactionStatus.COMPLETED,
            reference_number="SALE-002",
            transaction_date=date(2026, 10, 2),
            items=[
                SimpleNamespace(
                    id=uuid4(),
                    quantity=Decimal("1"),
                    conversion_factor=Decimal("1"),
                    total_amount=Decimal("30.00"),
                )
            ],
            payments=[SimpleNamespace(amount=Decimal("50.00"))],
        )
        allocation = SimpleNamespace(
            batch_id=uuid4(),
            batch=SimpleNamespace(name="Broiler batch A"),
            block_id=uuid4(),
            block=SimpleNamespace(name="Block 1"),
            quantity=2,
        )
        delivery_item = SimpleNamespace(
            id=uuid4(),
            transaction_item_id=item_id,
            quantity=Decimal("2"),
            batch_allocations=[allocation],
        )
        delivery = SimpleNamespace(
            id=uuid4(),
            delivered_date=date(2026, 10, 1),
            delivered_time=None,
            notes=None,
            items=[delivery_item],
        )
        transaction_repository = SimpleNamespace(
            get_sale_detail_by_id=AsyncMock(return_value=sale),
            list_by_farm=AsyncMock(return_value=[sale, other_sale]),
        )
        sale_delivery_repository = SimpleNamespace(
            get_delivered_quantities_by_transaction=AsyncMock(
                return_value={item_id: Decimal("2")}
            ),
            list_by_transaction=AsyncMock(return_value=[delivery]),
        )
        contact_repository = SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(name="Customer One"))
        )
        sale_return_repository = SimpleNamespace(
            get_credited_quantities_by_item=AsyncMock(return_value={})
        )
        transaction_refund_repository = SimpleNamespace(
            get_total_by_transaction=AsyncMock(return_value=Decimal("0.00"))
        )

        service = ChickenSaleDetailsService(
            transaction_repository=cast(TransactionRepository, transaction_repository),
            contact_repository=cast(ContactRepository, contact_repository),
            sale_delivery_repository=cast(
                SaleDeliveryRepository, sale_delivery_repository
            ),
            sale_return_repository=cast(SaleReturnRepository, sale_return_repository),
            transaction_refund_repository=cast(
                TransactionRefundRepository,
                transaction_refund_repository,
            ),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        details = await service.get_details(farm_id, sale_id)

        self.assertEqual(details.customer_name, "Customer One")
        self.assertEqual(details.transaction.reference_number, "SALE-001")
        self.assertEqual(details.transaction.balance_due, Decimal("40.00"))
        self.assertEqual(details.transaction.items[0].quantity_received, Decimal("2"))
        self.assertEqual(
            details.transaction.items[0].product_type,
            ProductType.CHICKENS,
        )
        self.assertEqual(len(details.transaction.payments), 1)
        self.assertEqual(details.deliveries[0].items[0].batch_allocations[0].batch_name, "Broiler batch A")
        self.assertEqual(details.deliveries[0].items[0].batch_allocations[0].block_name, "Block 1")
        self.assertEqual(details.customer_balance_total, Decimal("40.00"))
        self.assertEqual(details.customer_credit_total, Decimal("20.00"))


if __name__ == "__main__":
    unittest.main()

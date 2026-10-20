import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from app.core.exceptions import ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.repositories.contact_repository import ContactRepository
from app.repositories.purchase_replacement_repository import (
    PurchaseReplacementRepository,
)
from app.repositories.purchase_receipt_item_repository import (
    PurchaseReceiptItemRepository,
)
from app.repositories.purchase_receipt_repository import PurchaseReceiptRepository
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import (
    ChickenType,
    PaymentMethod,
    ProductType,
    TransactionStatus,
    TransactionType,
)
from app.services.chicken_purchase_details_service import (
    ChickenPurchaseDetailsService,
)


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        return False


class ChickenPurchaseDetailsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_purchase_details_include_receipt_progress_and_supplier_balances(self):
        farm_id = uuid4()
        purchase_id = uuid4()
        item_id = uuid4()
        supplier_id = uuid4()
        now = datetime.now()
        payment = SimpleNamespace(
            id=uuid4(),
            transaction_id=purchase_id,
            amount=Decimal("60.00"),
            payment_date=date(2026, 10, 1),
            payment_time=None,
            payment_method=PaymentMethod.CASH,
            reference_number=None,
            notes=None,
            created_at=now,
            updated_at=now,
        )
        item = SimpleNamespace(
            id=item_id,
            created_at=now,
            product_id=uuid4(),
            unit_id=uuid4(),
            product=SimpleNamespace(
                name="Pullets",
                product_type=ProductType.CHICKENS,
            ),
            unit=SimpleNamespace(name="each"),
            quantity=Decimal("10"),
            conversion_factor=Decimal("1"),
            chicken_type=ChickenType.LAYERS,
            unit_price=Decimal("5.00"),
            subtotal_amount=Decimal("50.00"),
            discount_amount=Decimal("0.00"),
            total_amount=Decimal("50.00"),
            notes=None,
            chicken_transaction_item=SimpleNamespace(
                batch=SimpleNamespace(
                    id=uuid4(),
                    name="Layer group 1",
                    hatch_date=date(2026, 9, 1),
                )
            ),
        )
        receipt = SimpleNamespace(
            id=uuid4(),
            transaction_id=purchase_id,
            received_date=date(2026, 10, 1),
            received_time=None,
            notes=None,
            created_at=now,
            items=[
                SimpleNamespace(
                    id=uuid4(),
                    transaction_item=item,
                    quantity=Decimal("4"),
                    block_allocations=[
                        SimpleNamespace(
                            block_id=uuid4(),
                            quantity=4,
                            block=SimpleNamespace(name="Brooder 1"),
                        )
                    ],
                )
            ],
        )
        transaction = SimpleNamespace(
            id=purchase_id,
            farm_id=farm_id,
            contact_id=supplier_id,
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            transaction_date=date(2026, 9, 30),
            reference_number="PUR-001",
            notes="First shipment",
            discount_type=None,
            discount_value=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            discount_reason=None,
            items=[item],
            payments=[payment],
            created_at=now,
            updated_at=now,
        )
        other_item = SimpleNamespace(total_amount=Decimal("100.00"))
        other_purchase = SimpleNamespace(
            id=uuid4(),
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            reference_number="PUR-002",
            transaction_date=date(2026, 10, 2),
            items=[other_item],
            payments=[],
        )
        credit_purchase = SimpleNamespace(
            id=uuid4(),
            transaction_type=TransactionType.PURCHASE,
            status=TransactionStatus.COMPLETED,
            reference_number="PUR-003",
            transaction_date=date(2026, 10, 3),
            items=[other_item],
            payments=[SimpleNamespace(amount=Decimal("130.00"))],
        )
        transaction_repository = SimpleNamespace(
            get_purchase_detail_by_id=self._async_return(transaction),
            list_by_farm=self._async_return(
                [transaction, other_purchase, credit_purchase]
            ),
        )
        receipt_item_repository = SimpleNamespace(
            get_received_quantities_by_transaction=self._async_return(
                {item_id: Decimal("4")}
            )
        )
        receipt_repository = SimpleNamespace(
            list_by_transaction=self._async_return([receipt])
        )
        contact_repository = SimpleNamespace(
            get_by_id=self._async_return(SimpleNamespace(name="Sunny Hatchery"))
        )
        purchase_return_repository = SimpleNamespace(
            get_total_credit_by_transaction=self._async_return_by_id(
                purchase_id,
                Decimal("5.00"),
                Decimal("0.00"),
            )
        )
        purchase_replacement_repository = SimpleNamespace(
            get_total_credit_applied_by_transaction=self._async_return_by_id(
                purchase_id,
                Decimal("5.00"),
                Decimal("0.00"),
            )
        )
        supplier_refund_repository = SimpleNamespace(
            get_total_by_transaction=self._async_return_by_id(
                purchase_id,
                Decimal("0.00"),
                Decimal("0.00"),
            )
        )
        service = ChickenPurchaseDetailsService(
            transaction_repository=cast(
                TransactionRepository,
                transaction_repository,
            ),
            contact_repository=cast(ContactRepository, contact_repository),
            receipt_repository=cast(PurchaseReceiptRepository, receipt_repository),
            receipt_item_repository=cast(
                PurchaseReceiptItemRepository,
                receipt_item_repository,
            ),
            purchase_return_repository=cast(
                PurchaseReturnRepository,
                purchase_return_repository,
            ),
            purchase_replacement_repository=cast(
                PurchaseReplacementRepository,
                purchase_replacement_repository,
            ),
            supplier_refund_repository=cast(
                PurchaseSupplierRefundRepository,
                supplier_refund_repository,
            ),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        response = await service.get_details(farm_id, purchase_id)

        self.assertEqual(response.transaction.items[0].quantity_received, Decimal("4"))
        self.assertEqual(response.transaction.items[0].quantity_remaining, Decimal("6"))
        self.assertEqual(response.transaction.items[0].product_name, "Pullets")
        self.assertEqual(
            response.transaction.items[0].product_type,
            ProductType.CHICKENS,
        )
        self.assertEqual(response.receipts[0].items[0].batch_name, "Layer group 1")
        self.assertEqual(
            response.receipts[0].items[0].block_allocations[0].block_name,
            "Brooder 1",
        )
        self.assertEqual(response.supplier_name, "Sunny Hatchery")
        self.assertEqual(response.transaction.amount_paid, Decimal("55.00"))
        self.assertEqual(response.transaction.balance_due, Decimal("0.00"))
        self.assertEqual(response.transaction.credit_balance, Decimal("10.00"))
        self.assertEqual(len(response.outstanding_supplier_balances), 3)
        self.assertEqual(response.supplier_balance_total, Decimal("100.00"))
        self.assertEqual(response.supplier_credit_total, Decimal("40.00"))
        self.assertEqual(
            response.outstanding_supplier_balances[0].credit_balance,
            Decimal("10.00"),
        )
        self.assertEqual(
            response.outstanding_supplier_balances[2].credit_balance,
            Decimal("30.00"),
        )

    async def test_purchase_details_reject_non_purchase_transactions(self):
        farm_id = uuid4()
        transaction = SimpleNamespace(transaction_type=TransactionType.SALE)
        transaction_repository = SimpleNamespace(
            get_purchase_detail_by_id=self._async_return(transaction)
        )
        service = ChickenPurchaseDetailsService(
            transaction_repository=cast(
                TransactionRepository,
                transaction_repository,
            ),
            contact_repository=cast(ContactRepository, SimpleNamespace()),
            receipt_repository=cast(PurchaseReceiptRepository, SimpleNamespace()),
            receipt_item_repository=cast(
                PurchaseReceiptItemRepository,
                SimpleNamespace(),
            ),
            purchase_return_repository=cast(
                PurchaseReturnRepository,
                SimpleNamespace(),
            ),
            purchase_replacement_repository=cast(
                PurchaseReplacementRepository,
                SimpleNamespace(),
            ),
            supplier_refund_repository=cast(
                PurchaseSupplierRefundRepository,
                SimpleNamespace(),
            ),
            unit_of_work=cast(UnitOfWork, FakeUnitOfWork()),
        )

        with self.assertRaises(ResourceNotFoundError):
            await service.get_details(farm_id, uuid4())

    @staticmethod
    def _async_return(value):
        async def return_value(*_args, **_kwargs):
            return value

        return return_value

    @staticmethod
    def _async_return_by_id(transaction_id, matching_value, other_value):
        async def return_value(requested_transaction_id):
            if requested_transaction_id == transaction_id:
                return matching_value
            return other_value

        return return_value

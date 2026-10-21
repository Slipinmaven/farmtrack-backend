from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.enums import TransactionStatus, TransactionType
from app.services.contact_history_service import ContactHistoryService


class FakeTotalRepository:
    def __init__(self, total: str, returned_quantities=None):
        self.total = Decimal(total)
        self.returned_quantities = returned_quantities or {}

    async def get_total_by_transaction(self, _transaction_id):
        return self.total

    async def get_total_credit_by_transaction(self, _transaction_id):
        return self.total

    async def get_credited_quantities_by_item(self, _transaction_id):
        return self.returned_quantities


class FakePurchaseReplacementRepository:
    async def get_total_credit_applied_by_transaction(self, _transaction_id):
        return Decimal("5.00")


def create_service() -> ContactHistoryService:
    return ContactHistoryService(
        contact_repository=None,
        transaction_repository=None,
        transaction_refund_repository=FakeTotalRepository("5.00"),
        sale_return_repository=FakeTotalRepository("10.00"),
        supplier_refund_repository=FakeTotalRepository("0.00"),
        purchase_return_repository=FakeTotalRepository("10.00"),
        purchase_replacement_repository=FakePurchaseReplacementRepository(),
        unit_of_work=None,
    )


def create_transaction(transaction_type: TransactionType, paid: str):
    return SimpleNamespace(
        id=uuid4(),
        transaction_type=transaction_type,
        status=TransactionStatus.COMPLETED,
        items=[
            SimpleNamespace(
                id=uuid4(),
                quantity=Decimal("1"),
                conversion_factor=Decimal("1"),
                total_amount=Decimal("100.00"),
            )
        ],
        payments=[SimpleNamespace(amount=Decimal(paid))],
    )


@pytest.mark.asyncio
async def test_sale_history_balance_includes_refunds_and_sale_credits():
    service = create_service()
    transaction = create_transaction(TransactionType.SALE, "40.00")
    service.sale_return_repository.returned_quantities = {
        transaction.items[0].id: Decimal("0.10")
    }

    balance = await service._calculate_balance(transaction)

    assert balance.balance_due == Decimal("55.00")
    assert balance.credit_balance == Decimal("0.00")


@pytest.mark.asyncio
async def test_purchase_history_balance_accounts_for_replacement_credit_use():
    service = create_service()
    transaction = create_transaction(TransactionType.PURCHASE, "120.00")

    balance = await service._calculate_balance(transaction)

    assert balance.balance_due == Decimal("0.00")
    assert balance.credit_balance == Decimal("25.00")

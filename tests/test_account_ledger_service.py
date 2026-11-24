from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.enums import TransactionStatus, TransactionType
from app.services.account_ledger_service import AccountLedgerService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class FakeTransactionRepository:
    def __init__(self, transactions):
        self.transactions = transactions

    async def list_for_account_ledger(self, _farm_id):
        return self.transactions


def create_transaction(
    *,
    transaction_type: TransactionType,
    transaction_date: date,
    contact_id,
    contact_name: str | None,
    amount: str,
    payments=(),
    settlements=(),
    unit_name: str | None = None,
):
    transaction_id = uuid4()
    return SimpleNamespace(
        id=transaction_id,
        transaction_type=transaction_type,
        status=TransactionStatus.COMPLETED,
        transaction_date=transaction_date,
        transaction_time=None,
        reference_number=f"REF-{str(transaction_id)[:8]}",
        contact_id=contact_id,
        contact=SimpleNamespace(name=contact_name) if contact_name else None,
        items=[
            SimpleNamespace(
                total_amount=Decimal(amount),
                product=SimpleNamespace(name="Feed"),
                quantity=Decimal("2"),
                unit=SimpleNamespace(name=unit_name) if unit_name else None,
            )
        ],
        payments=list(payments),
        settlements=list(settlements),
        sale_returns=[],
        refunds=[],
        purchase_returns=[],
        purchase_supplier_refunds=[],
        purchase_replacements=[],
    )


@pytest.mark.asyncio
async def test_ledger_separates_transactions_and_payment_events_and_carries_opening_balance():
    contact_id = uuid4()
    sale = create_transaction(
        transaction_type=TransactionType.SALE,
        transaction_date=date(2026, 10, 31),
        contact_id=contact_id,
        contact_name="Customer",
        amount="100.00",
    )
    sale.contact.contact_roles = [
        SimpleNamespace(role=SimpleNamespace(value="customer"))
    ]
    purchase = create_transaction(
        transaction_type=TransactionType.PURCHASE,
        transaction_date=date(2026, 11, 2),
        contact_id=contact_id,
        contact_name="Customer",
        amount="40.00",
        payments=[
            SimpleNamespace(
                id=uuid4(),
                amount=Decimal("10.00"),
                payment_date=date(2026, 11, 3),
                payment_time=time(10, 0),
                payment_method=SimpleNamespace(value="cash"),
                reference_number=None,
            )
        ],
    )
    service = AccountLedgerService(
        FakeTransactionRepository([sale, purchase]),
        FakeUnitOfWork(),
    )

    result = await service.get_ledger(
        uuid4(),
        contact_id=contact_id,
        from_date=date(2026, 11, 1),
        to_date=date(2026, 11, 30),
    )

    assert result.opening_balance == Decimal("100.00")
    assert result.closing_balance == Decimal("70.00")
    assert [event.event_type for event in result.events] == ["transaction", "payment"]
    assert result.events[0].running_balance == Decimal("60.00")
    assert result.events[1].amount == Decimal("10.00")
    assert result.events[1].running_balance == Decimal("70.00")
    assert result.accounts[0].roles == ["customer"]


@pytest.mark.asyncio
async def test_all_farm_ledger_keeps_transactions_without_a_contact():
    transaction = create_transaction(
        transaction_type=TransactionType.SALE,
        transaction_date=date(2026, 11, 5),
        contact_id=None,
        contact_name=None,
        amount="25.00",
    )
    service = AccountLedgerService(
        FakeTransactionRepository([transaction]),
        FakeUnitOfWork(),
    )

    result = await service.get_ledger(uuid4())

    assert len(result.events) == 1
    assert result.events[0].contact_id is None
    assert result.events[0].contact_name is None
    assert result.events[0].amount == Decimal("25.00")
    assert result.accounts[0].contact_name == "No contact assigned"


@pytest.mark.asyncio
async def test_sale_settlements_returns_and_refunds_are_distinct_signed_events():
    contact_id = uuid4()
    transaction = create_transaction(
        transaction_type=TransactionType.SALE,
        transaction_date=date(2026, 11, 5),
        contact_id=contact_id,
        contact_name="Customer",
        amount="100.00",
    )
    transaction.settlements = [
        SimpleNamespace(
            id=uuid4(),
            direction="contact_to_farm",
            total_value=Decimal("20.00"),
            settlement_date=date(2026, 11, 5),
            created_at=datetime(2026, 11, 5, 10, 0),
            lines=[
                {
                    "kind": "cash",
                    "amount": "5.00",
                    "value": "5.00",
                    "payment_method": "mpesa",
                    "reference_number": "SETTLE-1",
                },
                {
                    "kind": "service",
                    "description": "Transport",
                    "value": "15.00",
                }
            ],
            reason="Paid with goods",
        )
    ]
    transaction.sale_returns = [
        SimpleNamespace(
            id=uuid4(),
            return_date=date(2026, 11, 5),
            return_time=time(10, 0),
            reason="Damaged",
            items=[SimpleNamespace(credit_amount=Decimal("10.00"))],
        )
    ]
    transaction.refunds = [
        SimpleNamespace(
            id=uuid4(),
            refund_date=date(2026, 11, 5),
            refund_time=time(10, 0),
            payment_method=SimpleNamespace(value="mpesa"),
            amount=Decimal("5.00"),
            reference_number="MPESA-1",
            reason="Partial refund",
        )
    ]
    service = AccountLedgerService(
        FakeTransactionRepository([transaction]),
        FakeUnitOfWork(),
    )

    result = await service.get_ledger(uuid4(), contact_id=contact_id)

    assert [event.event_type for event in result.events] == [
        "transaction",
        "settlement",
        "return",
        "refund",
    ]
    assert [event.amount for event in result.events] == [
        Decimal("100.00"),
        Decimal("-20.00"),
        Decimal("-10.00"),
        Decimal("5.00"),
    ]
    assert "Service: Transport" in result.events[1].description
    assert result.events[1].cash_amount == Decimal("5.00")
    assert [
        (component.kind, component.label, component.amount)
        for component in result.events[1].components
    ] == [
        ("cash", "M-Pesa", Decimal("5.00")),
        ("service", "Transport", Decimal("15.00")),
    ]
    assert result.closing_balance == Decimal("75.00")


@pytest.mark.asyncio
async def test_purchase_payment_and_settlement_reduce_payable_to_zero():
    contact_id = uuid4()
    transaction = create_transaction(
        transaction_type=TransactionType.PURCHASE,
        transaction_date=date(2026, 11, 5),
        contact_id=contact_id,
        contact_name="Supplier",
        amount="170.00",
        unit_name="Bird",
        payments=[
            SimpleNamespace(
                id=uuid4(),
                amount=Decimal("100.00"),
                payment_date=date(2026, 11, 5),
                payment_time=time(10, 0),
                payment_method=SimpleNamespace(value="mpesa"),
                reference_number="PAY-1",
            )
        ],
        settlements=[
            SimpleNamespace(
                id=uuid4(),
                direction="farm_to_contact",
                total_value=Decimal("70.00"),
                settlement_date=date(2026, 11, 5),
                created_at=datetime(2026, 11, 5, 11, 0),
                lines=[
                    {
                        "kind": "cash",
                        "amount": "20.00",
                        "value": "20.00",
                        "payment_method": "mpesa",
                        "reference_number": "SETTLE-2",
                    },
                    {
                        "kind": "service",
                        "description": "Veterinary visit",
                        "value": "50.00",
                    },
                ],
                reason="I am paying him back",
            )
        ],
    )
    service = AccountLedgerService(
        FakeTransactionRepository([transaction]),
        FakeUnitOfWork(),
    )

    result = await service.get_ledger(uuid4(), contact_id=contact_id)

    assert [event.event_type for event in result.events] == [
        "transaction",
        "payment",
        "settlement",
    ]
    assert [event.amount for event in result.events] == [
        Decimal("-170.00"),
        Decimal("100.00"),
        Decimal("70.00"),
    ]
    assert result.closing_balance == Decimal("0.00")
    assert result.events[0].description == "Purchase · Feed: 2 birds"
    settlement = result.events[2]
    assert settlement.cash_amount == Decimal("20.00")
    assert [
        (component.kind, component.label, component.amount)
        for component in settlement.components
    ] == [
        ("cash", "M-Pesa", Decimal("20.00")),
        ("service", "Veterinary visit", Decimal("50.00")),
    ]


@pytest.mark.asyncio
async def test_settlement_overpayment_and_underpayment_keep_signed_balances():
    customer_id = uuid4()
    customer_sale = create_transaction(
        transaction_type=TransactionType.SALE,
        transaction_date=date(2026, 11, 5),
        contact_id=customer_id,
        contact_name="Customer",
        amount="100.00",
        settlements=[
            SimpleNamespace(
                id=uuid4(),
                direction="contact_to_farm",
                total_value=Decimal("60.00"),
                settlement_date=date(2026, 11, 6),
                created_at=datetime(2026, 11, 6, 10, 0),
                lines=[],
            )
        ],
    )
    customer_sale.contact.contact_roles = [
        SimpleNamespace(role=SimpleNamespace(value="customer"))
    ]

    supplier_id = uuid4()
    supplier_purchase = create_transaction(
        transaction_type=TransactionType.PURCHASE,
        transaction_date=date(2026, 11, 5),
        contact_id=supplier_id,
        contact_name="Supplier",
        amount="100.00",
        settlements=[
            SimpleNamespace(
                id=uuid4(),
                direction="farm_to_contact",
                total_value=Decimal("130.00"),
                settlement_date=date(2026, 11, 6),
                created_at=datetime(2026, 11, 6, 11, 0),
                lines=[],
            )
        ],
    )
    supplier_purchase.contact.contact_roles = [
        SimpleNamespace(role=SimpleNamespace(value="supplier"))
    ]
    service = AccountLedgerService(
        FakeTransactionRepository([customer_sale, supplier_purchase]),
        FakeUnitOfWork(),
    )

    result = await service.get_ledger(uuid4())

    balances = {account.contact_name: account.balance for account in result.accounts}
    assert balances == {
        "Customer": Decimal("40.00"),
        "Supplier": Decimal("30.00"),
    }
    assert sorted(event.amount for event in result.events) == sorted([
        Decimal("100.00"),
        Decimal("-100.00"),
        Decimal("-60.00"),
        Decimal("130.00"),
    ])

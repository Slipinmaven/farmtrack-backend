from decimal import Decimal
from uuid import UUID

from app.core.unit_of_work import UnitOfWork
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.receipt_history import (
    ReceiptHistoryFilters,
    ReceiptHistoryPayment,
    ReceiptHistoryResponse,
    ReceiptHistoryTransaction,
)


class ReceiptHistoryService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.unit_of_work = unit_of_work

    async def get_history(
        self,
        farm_id: UUID,
        filters: ReceiptHistoryFilters,
        offset: int,
        limit: int,
    ) -> ReceiptHistoryResponse:
        async with self.unit_of_work:
            transactions, total_count, completed_total = (
                await self.transaction_repository.get_receipt_history(
                    farm_id,
                    filters,
                    offset,
                    limit,
                )
            )
            items = [
                ReceiptHistoryTransaction(
                    id=transaction.id,
                    transaction_type=transaction.transaction_type,
                    status=transaction.status,
                    transaction_date=transaction.transaction_date,
                    reference_number=transaction.reference_number,
                    contact_name=(
                        transaction.contact.name
                        if transaction.contact is not None
                        else None
                    ),
                    product_names=sorted(
                        {item.product.name for item in transaction.items},
                        key=str.casefold,
                    ),
                    transaction_total=sum(
                        (item.total_amount for item in transaction.items),
                        Decimal("0.00"),
                    ),
                    payments=[
                        ReceiptHistoryPayment(
                            id=payment.id,
                            payment_number=index,
                            payment_date=payment.payment_date,
                            reference_number=payment.reference_number,
                            amount=payment.amount,
                            payment_method=payment.payment_method,
                        )
                        for index, payment in enumerate(
                            sorted(
                                transaction.payments,
                                key=lambda payment: (
                                    payment.payment_date,
                                    payment.created_at.timestamp()
                                    if getattr(payment, "created_at", None) is not None
                                    else 0,
                                    str(payment.id),
                                ),
                            ),
                            start=1,
                        )
                    ],
                )
                for transaction in transactions
            ]
            return ReceiptHistoryResponse(
                items=items,
                total_count=total_count,
                completed_total=completed_total,
                offset=offset,
                limit=limit,
            )

from decimal import Decimal
from uuid import UUID

from app.core.unit_of_work import UnitOfWork
from app.models.transaction_items import TransactionItem
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import TransactionStatus
from app.schemas.sales_report import (
    SalesReportFilters,
    SalesReportDay,
    SalesReportItem,
    SalesReportMonth,
    SalesReportProductSold,
    SalesReportResponse,
    SalesReportSummary,
)
from app.services.transaction_balance import (
    calculate_transaction_balance,
    get_settlement_adjustment,
)


class SalesReportService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        unit_of_work: UnitOfWork,
    ):
        self.transaction_repository = transaction_repository
        self.unit_of_work = unit_of_work

    async def get_report(
        self,
        farm_id: UUID,
        filters: SalesReportFilters,
        offset: int,
        limit: int,
        include_daily: bool = False,
    ) -> SalesReportResponse:
        status = {
            "completed": TransactionStatus.COMPLETED,
            "cancelled": TransactionStatus.CANCELLED,
            "all": None,
        }[filters.status]
        async with self.unit_of_work:
            (
                transactions,
                total_count,
                sellable_categories,
                monthly,
                daily,
                summary,
            ) = (
                await self.transaction_repository.get_sales_report(
                    farm_id,
                    from_date=filters.from_date,
                    to_date=filters.to_date,
                    category=filters.category,
                    status=status,
                    search=filters.search,
                    include_daily=include_daily,
                    offset=offset,
                    limit=limit,
                )
            )
            items = []
            for transaction in transactions:
                total = sum(
                    (item.total_amount for item in transaction.items),
                    Decimal("0.00"),
                )
                paid = sum(
                    (payment.amount for payment in transaction.payments),
                    Decimal("0.00"),
                )
                refunded = sum(
                    (refund.amount for refund in transaction.refunds),
                    Decimal("0.00"),
                )
                return_credits = sum(
                    (
                        item.credit_amount
                        for sale_return in transaction.sale_returns
                        for item in sale_return.items
                    ),
                    Decimal("0.00"),
                )
                balance = calculate_transaction_balance(
                    total,
                    paid,
                    refunded,
                    return_credits,
                    settlement_adjustment=get_settlement_adjustment(transaction),
                )
                items.append(
                    SalesReportItem(
                        id=transaction.id,
                        reference_number=transaction.reference_number,
                        transaction_date=transaction.transaction_date,
                        status=transaction.status,
                        customer_name=(
                            transaction.contact.name
                            if transaction.contact is not None
                            else None
                        ),
                        product_names=sorted(
                            {item.product.name for item in transaction.items}
                        ),
                        products_sold=self._products_sold(transaction.items),
                        categories=sorted(
                            {item.product.product_type for item in transaction.items},
                            key=lambda category: category.value,
                        ),
                        transaction_total=total,
                        amount_paid=balance.amount_paid,
                        balance_due=balance.balance_due,
                        credit_balance=balance.credit_balance,
                    )
                )
            return SalesReportResponse(
                items=items,
                sellable_categories=sellable_categories,
                total_count=total_count,
                offset=offset,
                limit=limit,
                summary=SalesReportSummary(
                    transaction_count=summary[0],
                    sales_total=summary[1],
                    amount_received=summary[2],
                    balance_due=summary[3],
                    monthly=[
                        SalesReportMonth(
                            month=row[0],
                            transaction_count=row[1],
                            sales_total=row[2],
                            amount_received=row[3],
                        )
                        for row in monthly
                    ],
                ),
                daily=[
                    SalesReportDay(
                        day=row[0],
                        transaction_count=row[1],
                        sales_total=row[2],
                    )
                    for row in daily
                ],
            )

    @staticmethod
    def _products_sold(
        items: list[TransactionItem],
    ) -> list[SalesReportProductSold]:
        quantities: dict[tuple[str, str | None], Decimal] = {}
        for item in items:
            key = (item.product.name, item.unit.name if item.unit else None)
            quantities[key] = quantities.get(key, Decimal("0")) + item.quantity
        return [
            SalesReportProductSold(
                name=name,
                quantity=quantity,
                unit_name=unit_name,
            )
            for (name, unit_name), quantity in sorted(
                quantities.items(),
                key=lambda entry: (
                    entry[0][0].casefold(),
                    entry[0][1] or "",
                ),
            )
        ]

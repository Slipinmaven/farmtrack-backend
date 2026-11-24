from decimal import Decimal
from uuid import UUID

from app.core.unit_of_work import UnitOfWork
from app.models.transaction_items import TransactionItem
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import ProductType, TransactionStatus
from app.schemas.sales_report import (
    PendingSaleDelivery,
    PendingSaleDeliveryItem,
    OutstandingBalanceSummary,
    OutstandingTransactionBalance,
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
                    from_time=filters.from_time,
                    to_time=filters.to_time,
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
                settlement_adjustment = get_settlement_adjustment(transaction)
                goods_settlement = sum(
                    (
                        Decimal(line["value"])
                        * (
                            Decimal("1.00")
                            if settlement.direction == "contact_to_farm"
                            else Decimal("-1.00")
                        )
                        for settlement in getattr(transaction, "settlements", ())
                        for line in settlement.lines
                        if line["kind"] == "goods"
                    ),
                    Decimal("0.00"),
                )
                service_settlement = sum(
                    (
                        Decimal(line["value"])
                        * (
                            Decimal("1.00")
                            if settlement.direction == "contact_to_farm"
                            else Decimal("-1.00")
                        )
                        for settlement in getattr(transaction, "settlements", ())
                        for line in settlement.lines
                        if line["kind"] == "service"
                    ),
                    Decimal("0.00"),
                )
                balance = calculate_transaction_balance(
                    total,
                    paid,
                    refunded,
                    return_credits,
                    settlement_adjustment=settlement_adjustment,
                )
                items.append(
                    SalesReportItem(
                        id=transaction.id,
                        reference_number=transaction.reference_number,
                        transaction_date=transaction.transaction_date,
                        transaction_time=getattr(
                            transaction,
                            "transaction_time",
                            None,
                        ),
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
                        return_credits=return_credits,
                        goods_settlement=goods_settlement,
                        service_settlement=service_settlement,
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
                    return_credits=summary[4],
                    goods_settlements=summary[5],
                    service_settlements=summary[6],
                    customer_credit=summary[7],
                    unallocated_amount=summary[8],
                    monthly=[
                        SalesReportMonth(
                            month=row[0],
                            transaction_count=row[1],
                            sales_total=row[2],
                            amount_received=row[3],
                            balance_due=row[4],
                            return_credits=row[5],
                            goods_settlements=row[6],
                            service_settlements=row[7],
                            customer_credit=row[8],
                            unallocated_amount=row[9],
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

    async def get_pending_deliveries(
        self,
        farm_id: UUID,
        *,
        limit: int,
    ) -> list[PendingSaleDelivery]:
        async with self.unit_of_work:
            transactions = (
                await self.transaction_repository.list_pending_sale_deliveries(
                    farm_id,
                    limit=limit,
                )
            )
            pending_sales = []
            for transaction in transactions:
                delivered_by_item: dict[UUID, Decimal] = {}
                for delivery in transaction.sale_deliveries:
                    for delivery_item in delivery.items:
                        delivered_by_item[delivery_item.transaction_item_id] = (
                            delivered_by_item.get(
                                delivery_item.transaction_item_id,
                                Decimal("0"),
                            )
                            + delivery_item.quantity
                        )

                cancelled_by_item: dict[UUID, Decimal] = {}
                for sale_return in transaction.sale_returns:
                    if sale_return.return_type != "undelivered_cancelled":
                        continue
                    for return_item in sale_return.items:
                        cancelled_by_item[return_item.transaction_item_id] = (
                            cancelled_by_item.get(
                                return_item.transaction_item_id,
                                Decimal("0"),
                            )
                            + return_item.quantity
                        )

                pending_items = []
                for item in transaction.items:
                    product_type = item.product.product_type
                    if product_type not in {ProductType.CHICKENS, ProductType.EGGS}:
                        continue
                    if (
                        product_type == ProductType.EGGS
                        and not transaction.fulfillment_required
                    ):
                        continue
                    conversion_factor = Decimal(item.conversion_factor)
                    remaining_base_quantity = (
                        Decimal(item.quantity) * conversion_factor
                        - delivered_by_item.get(item.id, Decimal("0"))
                        - cancelled_by_item.get(item.id, Decimal("0"))
                    )
                    if remaining_base_quantity <= 0:
                        continue
                    pending_items.append(
                        PendingSaleDeliveryItem(
                            product_name=item.product.name,
                            product_type=product_type,
                            quantity_remaining=(
                                remaining_base_quantity / conversion_factor
                            ),
                            quantity_remaining_base=remaining_base_quantity,
                            unit_name=item.unit.name if item.unit is not None else None,
                        )
                    )

                if pending_items:
                    pending_sales.append(
                        PendingSaleDelivery(
                            id=transaction.id,
                            reference_number=transaction.reference_number,
                            transaction_date=transaction.transaction_date,
                            customer_name=(
                                transaction.contact.name
                                if transaction.contact is not None
                                else None
                            ),
                            items=pending_items,
                        )
                    )
            return pending_sales

    async def get_outstanding_balances(
        self,
        farm_id: UUID,
        *,
        limit: int,
    ) -> OutstandingBalanceSummary:
        async with self.unit_of_work:
            rows = await self.transaction_repository.get_outstanding_balance_summary(
                farm_id,
                limit=limit,
            )
            items = [
                OutstandingTransactionBalance(
                    id=row.id,
                    transaction_type=row.transaction_type,
                    reference_number=row.reference_number,
                    transaction_date=row.transaction_date,
                    contact_name=row.contact_name,
                    balance_due=row.balance_due,
                    credit_balance=row.credit_balance,
                    account_balance_due=row.account_balance_due,
                    account_credit_balance=row.account_credit_balance,
                )
                for row in rows
            ]
            return OutstandingBalanceSummary(
                items=items,
                customer_balance_due_total=(
                    rows[0].customer_balance_due_total
                    if rows
                    else Decimal("0.00")
                ),
                supplier_balance_due_total=(
                    rows[0].supplier_balance_due_total
                    if rows
                    else Decimal("0.00")
                ),
                customer_credit_total=(
                    rows[0].customer_credit_total if rows else Decimal("0.00")
                ),
                supplier_credit_total=(
                    rows[0].supplier_credit_total if rows else Decimal("0.00")
                ),
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

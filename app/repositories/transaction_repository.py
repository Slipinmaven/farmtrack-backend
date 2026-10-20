from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transactions import Transaction
from app.models.transaction_settlements import TransactionSettlement
from app.models.transaction_items import TransactionItem
from app.models.transaction_payments import TransactionPayment
from app.models.transaction_refunds import TransactionRefund
from app.models.products import Product
from app.models.contact import Contact
from app.models.sale_return_items import SaleReturnItem
from app.models.sale_returns import SaleReturn
from app.models.transaction_settlements import TransactionSettlement
from app.schemas.enums import ProductType, TransactionStatus, TransactionType
from app.schemas.transaction import TransactionCreate


class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _query(self):
        return select(Transaction).options(
            selectinload(Transaction.items),
            selectinload(Transaction.payments),
            selectinload(Transaction.purchase_receipts),
            selectinload(Transaction.settlements),
        )

    def _purchase_detail_query(self):
        item_loader = selectinload(Transaction.items)
        return select(Transaction).options(
            item_loader.selectinload(TransactionItem.product),
            item_loader.selectinload(TransactionItem.unit),
            selectinload(Transaction.payments),
            selectinload(Transaction.settlements),
        )

    async def list_by_farm(
        self,
        farm_id: UUID,
        transaction_type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        contact_id: UUID | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Transaction]:
        query = self._query().where(Transaction.farm_id == farm_id)
        if transaction_type is not None:
            query = query.where(Transaction.transaction_type == transaction_type)
        if status is not None:
            query = query.where(Transaction.status == status)
        if from_date is not None:
            query = query.where(Transaction.transaction_date >= from_date)
        if to_date is not None:
            query = query.where(Transaction.transaction_date <= to_date)
        if contact_id is not None:
            query = query.where(Transaction.contact_id == contact_id)
        query = query.order_by(Transaction.transaction_date.desc(), Transaction.id)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count_by_farm(
        self,
        farm_id: UUID,
        contact_id: UUID,
    ) -> int:
        result = await self.session.execute(
            select(func.count(Transaction.id)).where(
                Transaction.farm_id == farm_id,
                Transaction.contact_id == contact_id,
            )
        )
        return int(result.scalar_one())

    async def get_by_id(self, farm_id: UUID, transaction_id: UUID) -> Transaction | None:
        result = await self.session.execute(
            self._query().where(
                Transaction.farm_id == farm_id,
                Transaction.id == transaction_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_purchase_detail_by_id(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> Transaction | None:
        result = await self.session.execute(
            self._purchase_detail_query().where(
                Transaction.farm_id == farm_id,
                Transaction.id == transaction_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_sale_detail_by_id(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> Transaction | None:
        result = await self.session.execute(
            self._purchase_detail_query()
            .options(selectinload(Transaction.contact))
            .where(
                Transaction.farm_id == farm_id,
                Transaction.id == transaction_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_sales_report(
        self,
        farm_id: UUID,
        *,
        from_date: date | None,
        to_date: date | None,
        category: ProductType | None,
        status: TransactionStatus | None,
        search: str | None,
        include_daily: bool,
        offset: int,
        limit: int,
    ) -> tuple[
        list[Transaction],
        int,
        list[ProductType],
        list[tuple[str, int, Decimal, Decimal]],
        list[tuple[date, int, Decimal]],
        tuple[int, Decimal, Decimal, Decimal],
    ]:
        scope_filters = [
            Transaction.farm_id == farm_id,
            Transaction.transaction_type == TransactionType.SALE,
        ]
        if from_date is not None:
            scope_filters.append(Transaction.transaction_date >= from_date)
        if to_date is not None:
            scope_filters.append(Transaction.transaction_date <= to_date)
        if category is not None:
            scope_filters.append(
                select(TransactionItem.id)
                .join(Product, Product.id == TransactionItem.product_id)
                .where(
                    TransactionItem.transaction_id == Transaction.id,
                    Product.product_type == category,
                )
                .exists()
            )
        normalized_search = search.strip() if search else ""
        if normalized_search:
            pattern = f"%{normalized_search}%"
            product_match = (
                select(TransactionItem.id)
                .join(Product, Product.id == TransactionItem.product_id)
                .where(
                    TransactionItem.transaction_id == Transaction.id,
                    Product.name.ilike(pattern),
                )
                .exists()
            )
            scope_filters.append(
                or_(
                    Transaction.reference_number.ilike(pattern),
                    Transaction.contact.has(Contact.name.ilike(pattern)),
                    product_match,
                )
            )

        page_filters = list(scope_filters)
        if status is not None:
            page_filters.append(Transaction.status == status)

        query = (
            self._query()
            .options(selectinload(Transaction.contact))
            .options(selectinload(Transaction.items).selectinload(TransactionItem.product))
            .options(selectinload(Transaction.items).selectinload(TransactionItem.unit))
            .options(selectinload(Transaction.refunds))
            .options(selectinload(Transaction.sale_returns).selectinload(SaleReturn.items))
            .where(*page_filters)
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc(), Transaction.id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(query)
        transactions = list(result.scalars().all())

        count_result = await self.session.execute(
            select(func.count(Transaction.id)).where(*page_filters)
        )
        total_count = int(count_result.scalar_one())

        sellable_categories_result = await self.session.execute(
            select(Product.product_type)
            .where(
                Product.farm_id == farm_id,
                Product.is_active.is_(True),
                Product.is_sellable.is_(True),
            )
            .distinct()
            .order_by(Product.product_type)
        )
        sellable_categories = list(sellable_categories_result.scalars().all())

        item_totals = (
            select(
                TransactionItem.transaction_id.label("transaction_id"),
                func.sum(TransactionItem.total_amount).label("total"),
            )
            .group_by(TransactionItem.transaction_id)
            .subquery()
        )
        payment_totals = (
            select(
                TransactionPayment.transaction_id.label("transaction_id"),
                func.sum(TransactionPayment.amount).label("paid"),
            )
            .group_by(TransactionPayment.transaction_id)
            .subquery()
        )
        refund_totals = (
            select(
                TransactionRefund.transaction_id.label("transaction_id"),
                func.sum(TransactionRefund.amount).label("refunded"),
            )
            .group_by(TransactionRefund.transaction_id)
            .subquery()
        )
        return_credit_totals = (
            select(
                SaleReturn.transaction_id.label("transaction_id"),
                func.sum(SaleReturnItem.credit_amount).label("credits"),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .group_by(SaleReturn.transaction_id)
            .subquery()
        )
        settlement_totals = (
            select(
                TransactionSettlement.transaction_id.label("transaction_id"),
                func.sum(
                    case(
                        (
                            TransactionSettlement.direction == "contact_to_farm",
                            TransactionSettlement.total_value,
                        ),
                        else_=-TransactionSettlement.total_value,
                    )
                ).label("settled"),
            )
            .group_by(TransactionSettlement.transaction_id)
            .subquery()
        )
        completed_filters = [
            *scope_filters,
            Transaction.status == TransactionStatus.COMPLETED,
        ]
        report_query = (
            select(
                func.to_char(
                    func.date_trunc("month", Transaction.transaction_date), "YYYY-MM"
                ).label("month"),
                func.count(Transaction.id).label("transaction_count"),
                func.coalesce(func.sum(item_totals.c.total), 0).label("sales_total"),
            )
            .join(item_totals, item_totals.c.transaction_id == Transaction.id)
            .where(*completed_filters)
            .group_by("month")
            .order_by("month")
        )
        monthly_result = await self.session.execute(report_query)
        monthly_values: dict[str, tuple[int, Decimal, Decimal]] = {}
        for row in monthly_result:
            monthly_values[row.month] = (
                int(row.transaction_count),
                row.sales_total,
                Decimal("0.00"),
            )
        received_query = (
            select(
                func.to_char(
                    func.date_trunc("month", TransactionPayment.payment_date),
                    "YYYY-MM",
                ).label("month"),
                func.sum(TransactionPayment.amount).label("amount_received"),
            )
            .join(
                Transaction,
                Transaction.id == TransactionPayment.transaction_id,
            )
            .where(*completed_filters)
            .group_by("month")
            .order_by("month")
        )
        received_result = await self.session.execute(received_query)
        for row in received_result:
            transaction_count, sales_total, _ = monthly_values.get(
                row.month,
                (0, Decimal("0.00"), Decimal("0.00")),
            )
            monthly_values[row.month] = (
                transaction_count,
                sales_total,
                row.amount_received,
            )
        monthly = [
            (month, values[0], values[1], values[2])
            for month, values in sorted(monthly_values.items())
        ]

        daily: list[tuple[date, int, Decimal]] = []
        if include_daily:
            daily_query = (
                select(
                    Transaction.transaction_date.label("day"),
                    func.count(Transaction.id).label("transaction_count"),
                    func.coalesce(func.sum(item_totals.c.total), 0).label("sales_total"),
                )
                .join(item_totals, item_totals.c.transaction_id == Transaction.id)
                .where(*completed_filters)
                .group_by(Transaction.transaction_date)
                .order_by(Transaction.transaction_date)
            )
            daily_result = await self.session.execute(daily_query)
            daily = [
                (row.day, int(row.transaction_count), row.sales_total)
                for row in daily_result
            ]

        summary_query = (
            select(
                func.count(Transaction.id),
                func.coalesce(func.sum(item_totals.c.total), 0),
                func.coalesce(func.sum(payment_totals.c.paid), 0),
                func.coalesce(
                    func.sum(
                        func.greatest(
                            item_totals.c.total
                            - func.coalesce(return_credit_totals.c.credits, 0)
                            - (
                                func.coalesce(payment_totals.c.paid, 0)
                                - func.coalesce(refund_totals.c.refunded, 0)
                                + func.coalesce(settlement_totals.c.settled, 0)
                            ),
                            0,
                        )
                    ),
                    0,
                ),
            )
            .join(item_totals, item_totals.c.transaction_id == Transaction.id)
            .outerjoin(
                payment_totals,
                payment_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                refund_totals,
                refund_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                return_credit_totals,
                return_credit_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                settlement_totals,
                settlement_totals.c.transaction_id == Transaction.id,
            )
            .where(*completed_filters)
        )
        summary_result = await self.session.execute(summary_query)
        summary_row = summary_result.one()
        summary = (
            int(summary_row[0]),
            summary_row[1],
            summary_row[2],
            summary_row[3],
        )
        return transactions, total_count, sellable_categories, monthly, daily, summary

    async def get_by_id_for_update(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> Transaction | None:
        result = await self.session.execute(
            self._query()
            .where(
                Transaction.farm_id == farm_id,
                Transaction.id == transaction_id,
            )
            .with_for_update(of=Transaction)
        )
        return result.scalar_one_or_none()

    async def create(self, farm_id: UUID, transaction_data: dict) -> Transaction:
        transaction = Transaction(farm_id=farm_id, **transaction_data)
        self.session.add(transaction)
        await self.session.flush()
        return transaction

    async def update(self, transaction: Transaction) -> Transaction:
        await self.session.flush()
        await self.session.refresh(transaction)
        return transaction

    async def delete(self, transaction: Transaction) -> None:
        await self.session.delete(transaction)
        await self.session.flush()

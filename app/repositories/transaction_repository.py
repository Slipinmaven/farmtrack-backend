from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, cast, func, or_, select, String
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transactions import Transaction
from app.models.transaction_settlements import TransactionSettlement
from app.models.transaction_items import TransactionItem
from app.models.transaction_payments import TransactionPayment
from app.models.transaction_refunds import TransactionRefund
from app.models.purchase_return_items import PurchaseReturnItem
from app.models.purchase_returns import PurchaseReturn
from app.models.purchase_replacement_items import PurchaseReplacementItem
from app.models.purchase_replacements import PurchaseReplacement
from app.models.purchase_supplier_refunds import PurchaseSupplierRefund
from app.models.products import Product
from app.models.contact import Contact
from app.models.sale_return_items import SaleReturnItem
from app.models.sale_returns import SaleReturn
from app.models.sale_deliveries import SaleDelivery
from app.models.sale_delivery_items import SaleDeliveryItem
from app.schemas.enums import ProductType, TransactionStatus, TransactionType
from app.schemas.receipt_history import ReceiptHistoryFilters
from app.schemas.transaction import TransactionCreate
from app.services.sales_reconciliation import (
    SalesReconciliationRecord,
    summarize_sales,
)


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

    async def list_for_account_ledger(self, farm_id: UUID) -> list[Transaction]:
        item_loader = selectinload(Transaction.items)
        query = (
            select(Transaction)
            .options(
                selectinload(Transaction.contact).selectinload(Contact.contact_roles),
                item_loader.selectinload(TransactionItem.product),
                item_loader.selectinload(TransactionItem.unit),
                selectinload(Transaction.payments),
                selectinload(Transaction.settlements),
                selectinload(Transaction.sale_returns).selectinload(SaleReturn.items),
                selectinload(Transaction.purchase_returns).selectinload(
                    PurchaseReturn.items
                ),
                selectinload(Transaction.purchase_supplier_refunds),
                selectinload(Transaction.refunds),
                selectinload(Transaction.purchase_replacements).selectinload(
                    PurchaseReplacement.items
                ),
            )
            .where(Transaction.farm_id == farm_id)
            .order_by(Transaction.transaction_date, Transaction.created_at, Transaction.id)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

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

    async def get_receipt_history(
        self,
        farm_id: UUID,
        filters: ReceiptHistoryFilters,
        offset: int,
        limit: int,
    ) -> tuple[list[Transaction], int, Decimal]:
        page_filters = [Transaction.farm_id == farm_id]
        if filters.transaction_type != "all":
            page_filters.append(
                Transaction.transaction_type
                == TransactionType(filters.transaction_type)
            )
        if filters.receipt_kind == "payment":
            page_filters.append(
                select(TransactionPayment.id)
                .where(TransactionPayment.transaction_id == Transaction.id)
                .exists()
            )
        if filters.status != "all":
            page_filters.append(Transaction.status == TransactionStatus(filters.status))
        if filters.from_date is not None:
            page_filters.append(Transaction.transaction_date >= filters.from_date)
        if filters.to_date is not None:
            page_filters.append(Transaction.transaction_date <= filters.to_date)

        normalized_search = filters.search.strip() if filters.search else ""
        if normalized_search:
            pattern = f"%{normalized_search}%"
            item_total = (
                select(func.coalesce(func.sum(TransactionItem.total_amount), 0))
                .where(TransactionItem.transaction_id == Transaction.id)
                .scalar_subquery()
            )
            product_match = (
                select(TransactionItem.id)
                .join(Product, Product.id == TransactionItem.product_id)
                .where(
                    TransactionItem.transaction_id == Transaction.id,
                    Product.name.ilike(pattern),
                )
                .exists()
            )
            payment_match = (
                select(TransactionPayment.id)
                .where(
                    TransactionPayment.transaction_id == Transaction.id,
                    or_(
                        TransactionPayment.reference_number.ilike(pattern),
                        TransactionPayment.notes.ilike(pattern),
                        cast(TransactionPayment.amount, String).ilike(pattern),
                        cast(TransactionPayment.payment_method, String).ilike(pattern),
                        cast(TransactionPayment.id, String).ilike(pattern),
                        cast(TransactionPayment.payment_date, String).ilike(pattern),
                    ),
                )
                .exists()
            )
            page_filters.append(
                or_(
                    Transaction.reference_number.ilike(pattern),
                    cast(Transaction.id, String).ilike(pattern),
                    cast(Transaction.transaction_date, String).ilike(pattern),
                    Transaction.notes.ilike(pattern),
                    cast(Transaction.status, String).ilike(pattern),
                    cast(item_total, String).ilike(pattern),
                    Transaction.contact.has(
                        or_(
                            Contact.name.ilike(pattern),
                            Contact.phone.ilike(pattern),
                            Contact.email.ilike(pattern),
                        )
                    ),
                    product_match,
                    payment_match,
                )
            )

        result = await self.session.execute(
            select(Transaction)
            .options(
                selectinload(Transaction.contact),
                selectinload(Transaction.items).selectinload(TransactionItem.product),
                selectinload(Transaction.payments),
            )
            .where(*page_filters)
            .order_by(
                Transaction.transaction_date.desc(),
                Transaction.created_at.desc(),
                Transaction.id,
            )
            .offset(offset)
            .limit(limit)
        )
        transactions = list(result.scalars().all())
        count_result = await self.session.execute(
            select(func.count(Transaction.id)).where(*page_filters)
        )
        total_result = await self.session.execute(
            select(func.coalesce(func.sum(TransactionItem.total_amount), 0))
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .where(
                *page_filters,
                Transaction.status == TransactionStatus.COMPLETED,
            )
        )
        return (
            transactions,
            int(count_result.scalar_one()),
            Decimal(total_result.scalar_one()),
        )

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
        list[
            tuple[
                str,
                int,
                Decimal,
                Decimal,
                Decimal,
                Decimal,
                Decimal,
                Decimal,
                Decimal,
            ]
        ],
        list[tuple[date, int, Decimal]],
        tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal],
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
        completed_filters = [
            *scope_filters,
            Transaction.status == TransactionStatus.COMPLETED,
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
                Transaction.id,
                Transaction.transaction_date,
                Transaction.status,
                item_totals.c.total,
                func.coalesce(payment_totals.c.paid, 0).label("paid"),
                func.coalesce(refund_totals.c.refunded, 0).label("refunded"),
                func.coalesce(return_credit_totals.c.credits, 0).label("credits"),
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
            .where(*completed_filters)
        )
        summary_rows = (await self.session.execute(summary_query)).all()
        settlement_query = (
            select(
                TransactionSettlement.transaction_id,
                TransactionSettlement.direction,
                TransactionSettlement.total_value,
                TransactionSettlement.lines,
            )
            .join(
                Transaction,
                Transaction.id == TransactionSettlement.transaction_id,
            )
            .where(*completed_filters)
        )
        settlements_by_transaction: dict[UUID, list[dict[str, Any]]] = {}
        for settlement in (await self.session.execute(settlement_query)).all():
            settlements_by_transaction.setdefault(
                settlement.transaction_id, []
            ).append(
                {
                    "direction": settlement.direction,
                    "total_value": settlement.total_value,
                    "lines": settlement.lines,
                }
            )
        summary_records = [
            SalesReconciliationRecord(
                transaction_date=row.transaction_date,
                status=row.status,
                transaction_total=row.total,
                payments=row.paid,
                refunds=row.refunded,
                return_credits=row.credits,
                settlements=tuple(settlements_by_transaction.get(row.id, ())),
            )
            for row in summary_rows
        ]
        summary_values = summarize_sales(
            summary_records,
            from_date=from_date,
            to_date=to_date,
        )
        monthly_records: dict[str, list[SalesReconciliationRecord]] = {}
        for record in summary_records:
            month = record.transaction_date.strftime("%Y-%m")
            monthly_records.setdefault(month, []).append(record)
        monthly = []
        for month, records in sorted(monthly_records.items()):
            month_summary = summarize_sales(
                records,
                from_date=None,
                to_date=None,
            )
            monthly.append(
                (
                    month,
                    month_summary.transaction_count,
                    month_summary.sales_total,
                    month_summary.amount_received,
                    month_summary.balance_due,
                    month_summary.return_credits,
                    month_summary.goods_settlements,
                    month_summary.service_settlements,
                    month_summary.customer_credit,
                    month_summary.unallocated_amount,
                )
            )
        summary = (
            summary_values.transaction_count,
            summary_values.sales_total,
            summary_values.amount_received,
            summary_values.balance_due,
            summary_values.return_credits,
            summary_values.goods_settlements,
            summary_values.service_settlements,
            summary_values.customer_credit,
            summary_values.unallocated_amount,
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

    async def list_pending_sale_deliveries(
        self,
        farm_id: UUID,
        *,
        limit: int,
    ) -> list[Transaction]:
        delivered_quantities = (
            select(
                SaleDeliveryItem.transaction_item_id.label("transaction_item_id"),
                func.sum(SaleDeliveryItem.quantity).label("quantity"),
            )
            .join(
                SaleDelivery,
                SaleDelivery.id == SaleDeliveryItem.sale_delivery_id,
            )
            .group_by(SaleDeliveryItem.transaction_item_id)
            .subquery()
        )
        cancelled_quantities = (
            select(
                SaleReturnItem.transaction_item_id.label("transaction_item_id"),
                func.sum(SaleReturnItem.quantity).label("quantity"),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .where(SaleReturn.return_type == "undelivered_cancelled")
            .group_by(SaleReturnItem.transaction_item_id)
            .subquery()
        )
        outstanding_quantity = (
            TransactionItem.quantity * TransactionItem.conversion_factor
            - func.coalesce(delivered_quantities.c.quantity, 0)
            - func.coalesce(cancelled_quantities.c.quantity, 0)
        )
        pending_item_exists = (
            select(TransactionItem.id)
            .join(Product, Product.id == TransactionItem.product_id)
            .outerjoin(
                delivered_quantities,
                delivered_quantities.c.transaction_item_id == TransactionItem.id,
            )
            .outerjoin(
                cancelled_quantities,
                cancelled_quantities.c.transaction_item_id == TransactionItem.id,
            )
            .where(
                TransactionItem.transaction_id == Transaction.id,
                or_(
                    Product.product_type == ProductType.CHICKENS,
                    and_(
                        Product.product_type == ProductType.EGGS,
                        Transaction.fulfillment_required.is_(True),
                    ),
                ),
                outstanding_quantity > 0,
            )
            .exists()
        )
        query = (
            select(Transaction)
            .options(
                selectinload(Transaction.contact),
                selectinload(Transaction.items).selectinload(TransactionItem.product),
                selectinload(Transaction.items).selectinload(TransactionItem.unit),
                selectinload(Transaction.sale_deliveries).selectinload(
                    SaleDelivery.items
                ),
                selectinload(Transaction.sale_returns).selectinload(SaleReturn.items),
            )
            .where(
                Transaction.farm_id == farm_id,
                Transaction.transaction_type == TransactionType.SALE,
                Transaction.status == TransactionStatus.COMPLETED,
                pending_item_exists,
            )
            .order_by(
                Transaction.transaction_date.desc(),
                Transaction.created_at.desc(),
                Transaction.id,
            )
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_outstanding_balance_summary(
        self,
        farm_id: UUID,
        *,
        limit: int,
    ) -> list[Row[Any]]:
        farm_transaction_ids = select(Transaction.id).where(
            Transaction.farm_id == farm_id
        )
        item_totals = (
            select(
                TransactionItem.transaction_id.label("transaction_id"),
                func.sum(TransactionItem.total_amount).label("total"),
            )
            .where(TransactionItem.transaction_id.in_(farm_transaction_ids))
            .group_by(TransactionItem.transaction_id)
            .subquery()
        )
        payment_totals = (
            select(
                TransactionPayment.transaction_id.label("transaction_id"),
                func.sum(TransactionPayment.amount).label("paid"),
            )
            .where(TransactionPayment.transaction_id.in_(farm_transaction_ids))
            .group_by(TransactionPayment.transaction_id)
            .subquery()
        )
        sales_refund_totals = (
            select(
                TransactionRefund.transaction_id.label("transaction_id"),
                func.sum(TransactionRefund.amount).label("refunded"),
            )
            .where(TransactionRefund.transaction_id.in_(farm_transaction_ids))
            .group_by(TransactionRefund.transaction_id)
            .subquery()
        )
        supplier_refund_totals = (
            select(
                PurchaseSupplierRefund.transaction_id.label("transaction_id"),
                func.sum(PurchaseSupplierRefund.amount).label("refunded"),
            )
            .where(
                PurchaseSupplierRefund.transaction_id.in_(farm_transaction_ids)
            )
            .group_by(PurchaseSupplierRefund.transaction_id)
            .subquery()
        )
        sale_credit_totals = (
            select(
                SaleReturn.transaction_id.label("transaction_id"),
                func.sum(SaleReturnItem.credit_amount).label("credits"),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .where(SaleReturn.transaction_id.in_(farm_transaction_ids))
            .group_by(SaleReturn.transaction_id)
            .subquery()
        )
        purchase_credit_totals = (
            select(
                PurchaseReturn.transaction_id.label("transaction_id"),
                func.sum(PurchaseReturnItem.credit_amount).label("credits"),
            )
            .join(
                PurchaseReturn,
                PurchaseReturn.id == PurchaseReturnItem.purchase_return_id,
            )
            .where(PurchaseReturn.transaction_id.in_(farm_transaction_ids))
            .group_by(PurchaseReturn.transaction_id)
            .subquery()
        )
        replacement_credit_totals = (
            select(
                PurchaseReplacement.transaction_id.label("transaction_id"),
                func.sum(
                    PurchaseReplacementItem.credit_applied_amount
                ).label("credits"),
            )
            .join(
                PurchaseReplacement,
                PurchaseReplacement.id
                == PurchaseReplacementItem.purchase_replacement_id,
            )
            .where(PurchaseReplacement.transaction_id.in_(farm_transaction_ids))
            .group_by(PurchaseReplacement.transaction_id)
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
            .where(
                TransactionSettlement.transaction_id.in_(farm_transaction_ids)
            )
            .group_by(TransactionSettlement.transaction_id)
            .subquery()
        )
        total = func.coalesce(item_totals.c.total, 0)
        paid = (
            func.coalesce(payment_totals.c.paid, 0)
            - case(
                (
                    Transaction.transaction_type == TransactionType.SALE,
                    func.coalesce(sales_refund_totals.c.refunded, 0),
                ),
                else_=func.coalesce(supplier_refund_totals.c.refunded, 0),
            )
            + case(
                (
                    Transaction.transaction_type == TransactionType.SALE,
                    func.coalesce(settlement_totals.c.settled, 0),
                ),
                else_=-func.coalesce(settlement_totals.c.settled, 0),
            )
            - case(
                (
                    Transaction.transaction_type == TransactionType.PURCHASE,
                    func.coalesce(replacement_credit_totals.c.credits, 0),
                ),
                else_=0,
            )
        )
        return_credits = case(
            (
                Transaction.transaction_type == TransactionType.SALE,
                func.coalesce(sale_credit_totals.c.credits, 0),
            ),
            else_=func.coalesce(purchase_credit_totals.c.credits, 0),
        )
        adjusted_total = total - return_credits
        adjusted_total = func.greatest(adjusted_total, 0)
        balance_due = func.greatest(adjusted_total - paid, 0)
        credit_balance = func.greatest(paid - adjusted_total, 0)
        account_balance_due = func.sum(balance_due).over(
            partition_by=[
                func.coalesce(Transaction.contact_id, Transaction.id),
                Transaction.transaction_type,
            ]
        )
        account_credit_balance = func.sum(credit_balance).over(
            partition_by=[
                func.coalesce(Transaction.contact_id, Transaction.id),
                Transaction.transaction_type,
            ]
        )
        customer_balance_due_total = func.sum(
            case(
                (Transaction.transaction_type == TransactionType.SALE, balance_due),
                else_=0,
            )
        ).over()
        supplier_balance_due_total = func.sum(
            case(
                (
                    Transaction.transaction_type == TransactionType.PURCHASE,
                    balance_due,
                ),
                else_=0,
            )
        ).over()
        customer_credit_total = func.sum(
            case(
                (
                    Transaction.transaction_type == TransactionType.SALE,
                    credit_balance,
                ),
                else_=0,
            )
        ).over()
        supplier_credit_total = func.sum(
            case(
                (
                    Transaction.transaction_type == TransactionType.PURCHASE,
                    credit_balance,
                ),
                else_=0,
            )
        ).over()
        query = (
            select(
                Transaction.id,
                Transaction.transaction_type,
                Transaction.reference_number,
                Transaction.transaction_date,
                Contact.name.label("contact_name"),
                balance_due.label("balance_due"),
                credit_balance.label("credit_balance"),
                account_balance_due.label("account_balance_due"),
                account_credit_balance.label("account_credit_balance"),
                customer_balance_due_total.label("customer_balance_due_total"),
                supplier_balance_due_total.label("supplier_balance_due_total"),
                customer_credit_total.label("customer_credit_total"),
                supplier_credit_total.label("supplier_credit_total"),
            )
            .join(item_totals, item_totals.c.transaction_id == Transaction.id)
            .outerjoin(
                payment_totals,
                payment_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                sales_refund_totals,
                sales_refund_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                supplier_refund_totals,
                supplier_refund_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                sale_credit_totals,
                sale_credit_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                purchase_credit_totals,
                purchase_credit_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                replacement_credit_totals,
                replacement_credit_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(
                settlement_totals,
                settlement_totals.c.transaction_id == Transaction.id,
            )
            .outerjoin(Contact, Contact.id == Transaction.contact_id)
            .where(
                Transaction.farm_id == farm_id,
                Transaction.status == TransactionStatus.COMPLETED,
                or_(balance_due > 0, credit_balance > 0),
            )
            .order_by(
                balance_due.desc(),
                Transaction.transaction_date,
                Transaction.created_at,
                Transaction.id,
            )
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.all())

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

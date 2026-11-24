from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.blocks import Block
from app.models.contact import Contact
from app.models.expense_payment import ExpensePayment
from app.models.expenses import Expense


class ExpenseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, farm_id: UUID, data: dict) -> Expense:
        expense = Expense(farm_id=farm_id, **data)
        expense.payments = []
        self.session.add(expense)
        await self.session.flush()
        return expense

    async def get_by_id_for_update(self, farm_id: UUID, expense_id: UUID) -> Expense | None:
        result = await self.session.execute(
            select(Expense)
            .where(Expense.farm_id == farm_id, Expense.id == expense_id)
            .with_for_update(of=Expense)
        )
        return result.scalar_one_or_none()

    async def get_by_purchase_transaction(
        self,
        transaction_id: UUID,
    ) -> Expense | None:
        result = await self.session.execute(
            select(Expense)
            .where(Expense.purchase_transaction_id == transaction_id)
            .options(selectinload(Expense.payments))
            .with_for_update(of=Expense)
        )
        return result.scalar_one_or_none()

    async def list_by_farm(
        self,
        farm_id: UUID,
        *,
        category: str | list[str] | None = None,
        contact_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        search: str | None = None,
        payment_status: str | None = None,
        block_id: UUID | None = None,
        exclude_cancelled: bool = False,
        exclude_purchase_linked: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Expense], int]:
        net_paid = (
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (ExpensePayment.kind == "payment", ExpensePayment.amount),
                            else_=-ExpensePayment.amount,
                        )
                    ),
                    0,
                )
            )
            .where(ExpensePayment.expense_id == Expense.id)
            .correlate(Expense)
            .scalar_subquery()
        )
        query = select(Expense).where(Expense.farm_id == farm_id)
        if exclude_cancelled:
            query = query.where(Expense.canceled_at.is_(None))
        if exclude_purchase_linked:
            query = query.where(Expense.purchase_transaction_id.is_(None))
        if category is not None:
            if isinstance(category, list):
                query = query.where(Expense.category.in_(category))
            else:
                query = query.where(Expense.category == category)
        if contact_id is not None:
            query = query.where(Expense.contact_id == contact_id)
        if block_id is not None:
            query = query.where(Expense.block_id == block_id)
        if from_date is not None:
            query = query.where(Expense.expense_date >= from_date)
        if to_date is not None:
            query = query.where(Expense.expense_date <= to_date)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Expense.name.ilike(pattern),
                    Expense.category.ilike(pattern),
                    Expense.notes.ilike(pattern),
                    Expense.receipt_reference.ilike(pattern),
                    Expense.reference_number.ilike(pattern),
                    Expense.contact.has(Contact.name.ilike(pattern)),
                    Expense.block.has(Block.name.ilike(pattern)),
                    Expense.payments.any(ExpensePayment.reference_number.ilike(pattern)),
                )
            )
        if payment_status == "cancelled":
            query = query.where(Expense.canceled_at.is_not(None))
        elif payment_status in {"paid", "partial", "unpaid"}:
            query = query.where(Expense.canceled_at.is_(None))
            if payment_status == "paid":
                query = query.where(net_paid >= Expense.amount)
            elif payment_status == "partial":
                query = query.where(net_paid > 0, net_paid < Expense.amount)
            else:
                query = query.where(net_paid <= 0)
        count_result = await self.session.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        total_count = count_result.scalar_one()
        result = await self.session.execute(
            query.options(
                selectinload(Expense.payments),
            )
            .order_by(
                Expense.expense_date.desc(),
                Expense.created_at.desc(),
                Expense.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().unique().all()), total_count

    async def summarize_by_farm(
        self,
        farm_id: UUID,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[tuple[str, int, Decimal, Decimal, Decimal]]:
        payment_totals = (
            select(
                ExpensePayment.expense_id.label("expense_id"),
                func.sum(
                    case(
                        (ExpensePayment.kind == "payment", ExpensePayment.amount),
                        else_=-ExpensePayment.amount,
                    )
                ).label("net_paid"),
            )
            .join(Expense, Expense.id == ExpensePayment.expense_id)
            .where(
                Expense.farm_id == farm_id,
                Expense.canceled_at.is_(None),
            )
            .group_by(ExpensePayment.expense_id)
        )
        if from_date is not None:
            payment_totals = payment_totals.where(Expense.expense_date >= from_date)
        if to_date is not None:
            payment_totals = payment_totals.where(Expense.expense_date <= to_date)
        payment_totals = payment_totals.subquery()
        net_paid = func.coalesce(payment_totals.c.net_paid, 0)
        amount_paid = case(
            (net_paid < 0, 0),
            (net_paid > Expense.amount, Expense.amount),
            else_=net_paid,
        )
        balance_due = case(
            (Expense.amount > amount_paid, Expense.amount - amount_paid),
            else_=0,
        )
        query = (
            select(
                Expense.category,
                func.count(Expense.id),
                func.sum(Expense.amount),
                func.sum(amount_paid),
                func.sum(balance_due),
            )
            .outerjoin(
                payment_totals,
                payment_totals.c.expense_id == Expense.id,
            )
            .where(
                Expense.farm_id == farm_id,
                Expense.canceled_at.is_(None),
            )
            .group_by(Expense.category)
        )
        if from_date is not None:
            query = query.where(Expense.expense_date >= from_date)
        if to_date is not None:
            query = query.where(Expense.expense_date <= to_date)
        result = await self.session.execute(query)
        return list(result.all())
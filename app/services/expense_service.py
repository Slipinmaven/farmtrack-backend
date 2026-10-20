import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.block_repository import BlockRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.expense_category_repository import ExpenseCategoryRepository
from app.repositories.expense_payment_repository import ExpensePaymentRepository
from app.repositories.expense_repository import ExpenseRepository
from app.schemas.enums import ActivityEntityType, ActivityType, PaymentMethod
from app.schemas.expense import (
    ExpenseCancelRequest,
    ExpenseCategoryCreateRequest,
    ExpenseCategoryResponse,
    ExpenseCategoryUpdateRequest,
    ExpenseCreateRequest,
    ExpenseListResponse,
    ExpensePaymentCreateRequest,
    ExpensePaymentResponse,
    ExpenseRefundCreateRequest,
    ExpenseResponse,
    ExpenseSummaryCategory,
    ExpenseSummaryResponse,
    ExpenseUpdateRequest,
)
from app.services.activity_service import ActivityService

CENT = Decimal("0.01")
DEFAULT_EXPENSE_CATEGORIES = (
    ("feed_and_nutrition", "Feed and nutrition"),
    ("medication_veterinary", "Medication and veterinary"),
    ("labour", "Labour"),
    ("utilities", "Utilities"),
    ("transport", "Transport"),
    ("repairs_maintenance", "Repairs and maintenance"),
    ("equipment", "Equipment"),
    ("housing_facilities", "Housing and facilities"),
    ("packaging", "Packaging"),
    ("administration", "Administration"),
    ("other", "Other"),
)


class ExpenseService:
    def __init__(
        self,
        expense_repository: ExpenseRepository,
        contact_repository: ContactRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        category_repository: ExpenseCategoryRepository | None = None,
        payment_repository: ExpensePaymentRepository | None = None,
        block_repository: BlockRepository | None = None,
    ) -> None:
        self.expense_repository = expense_repository
        self.contact_repository = contact_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.category_repository = category_repository
        self.payment_repository = payment_repository
        self.block_repository = block_repository

    async def create_expense(
        self,
        farm: Farm,
        request: ExpenseCreateRequest,
    ) -> ExpenseResponse:
        async with self.unit_of_work:
            category = await self._require_category(farm.id, request.category)
            contact = await self._resolve_contact(farm.id, request.contact_id)
            block = await self._resolve_block(farm.id, request.block_id)
            initial_payment = request.initial_payment
            if initial_payment and initial_payment.amount > request.amount:
                raise ConflictError("The initial payment cannot exceed the expense total.")

            expense = await self.expense_repository.create(
                farm.id,
                {
                    "name": request.name.strip(),
                    "category": category.key,
                    "amount": request.amount.quantize(CENT),
                    "expense_date": request.expense_date,
                    "contact_id": request.contact_id,
                    "block_id": request.block_id,
                    "receipt_reference": _strip_or_none(request.receipt_reference),
                    "payment_method": (
                        initial_payment.payment_method
                        if initial_payment
                        else PaymentMethod.CASH
                    ),
                    "reference_number": (
                        _strip_or_none(initial_payment.reference_number)
                        if initial_payment
                        else None
                    ),
                    "notes": _strip_or_none(request.notes),
                },
            )
            expense.contact = contact
            expense.block = block
            if initial_payment is not None:
                await self._create_payment(
                    expense,
                    initial_payment,
                )
            await self._record_activity(
                farm,
                expense,
                "expense_recorded",
                {
                    "name": expense.name,
                    "category": category.name,
                    "amount": str(expense.amount),
                    "expense_date": expense.expense_date.isoformat(),
                    "contact_name": contact.name if contact else None,
                    "block_name": block.name if block else None,
                    "notes": expense.notes,
                    "payment_status": _payment_status(
                        expense.amount,
                        _net_payments(expense.payments),
                        expense.canceled_at,
                    ),
                },
            )
            await self.unit_of_work.commit()
            return self._to_response(expense, category.name)

    async def list_expenses(
        self,
        farm: Farm,
        *,
        category: str | None = None,
        contact_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        search: str | None = None,
        payment_status: str | None = None,
        block_id: UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> ExpenseListResponse:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ConflictError("from_date must be on or before to_date.")
        async with self.unit_of_work:
            categories = await self._list_categories(farm.id, include_inactive=True)
            category_names = {item.key: item.name for item in categories}
            expenses, total_count = await self.expense_repository.list_by_farm(
                farm.id,
                category=category,
                contact_id=contact_id,
                from_date=from_date,
                to_date=to_date,
                search=search,
                payment_status=payment_status,
                block_id=block_id,
                offset=offset,
                limit=limit,
            )
            items = [
                self._to_response(
                    expense,
                    category_names.get(expense.category, expense.category),
                )
                for expense in expenses
            ]
            await self.unit_of_work.commit()
            return ExpenseListResponse(
                items=items,
                total_count=total_count,
                offset=offset,
                limit=limit,
            )

    async def get_expense(self, farm: Farm, expense_id: UUID) -> ExpenseResponse:
        async with self.unit_of_work:
            expense = await self.expense_repository.get_by_id_for_update(
                farm.id,
                expense_id,
            )
            if expense is None:
                raise ResourceNotFoundError("Expense not found for this farm.")
            category = await self._require_category(
                farm.id,
                expense.category,
                include_inactive=True,
            )
            response = self._to_response(expense, category.name)
            await self.unit_of_work.commit()
            return response

    async def get_expense_summary(
        self,
        farm: Farm,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> ExpenseSummaryResponse:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ConflictError("from_date must be on or before to_date.")
        async with self.unit_of_work:
            categories = await self._list_categories(
                farm.id,
                include_inactive=True,
            )
            category_names = {item.key: item.name for item in categories}
            rows = await self.expense_repository.summarize_by_farm(
                farm.id,
                from_date=from_date,
                to_date=to_date,
            )
            summary_categories = [
                ExpenseSummaryCategory(
                    key=key,
                    name=category_names.get(key, key),
                    expense_count=count,
                    total_amount=total,
                    amount_paid=paid,
                    balance_due=balance,
                )
                for key, count, total, paid, balance in rows
            ]
            result = ExpenseSummaryResponse(
                expense_count=sum(item.expense_count for item in summary_categories),
                total_amount=sum(
                    (item.total_amount for item in summary_categories),
                    Decimal("0.00"),
                ),
                amount_paid=sum(
                    (item.amount_paid for item in summary_categories),
                    Decimal("0.00"),
                ),
                balance_due=sum(
                    (item.balance_due for item in summary_categories),
                    Decimal("0.00"),
                ),
                categories=summary_categories,
            )
            await self.unit_of_work.commit()
            return result

    async def record_payment(
        self,
        farm: Farm,
        expense_id: UUID,
        request: ExpensePaymentCreateRequest,
    ) -> ExpenseResponse:
        async with self.unit_of_work:
            expense = await self._get_locked_expense(farm.id, expense_id)
            self._ensure_manually_managed(expense)
            if expense.canceled_at is not None:
                raise ConflictError("A cancelled expense cannot receive payments.")
            remaining = expense.amount - _net_payments(expense.payments)
            if request.amount.quantize(CENT) > remaining:
                raise ConflictError(
                    f"Payment exceeds the remaining balance of {remaining:.2f}."
                )
            await self._create_payment(expense, request)
            expense.payment_method = request.payment_method
            expense.reference_number = _strip_or_none(request.reference_number)
            category = await self._require_category(
                farm.id,
                expense.category,
                include_inactive=True,
            )
            await self._record_activity(
                farm,
                expense,
                "expense_payment_recorded",
                {
                    "name": expense.name,
                    "amount": str(request.amount),
                    "payment_date": request.payment_date.isoformat(),
                    "payment_method": request.payment_method.value,
                    "reference_number": request.reference_number,
                    "event_action": "payment_recorded",
                },
            )
            await self.unit_of_work.commit()
            return self._to_response(expense, category.name)

    async def record_refund(
        self,
        farm: Farm,
        expense_id: UUID,
        request: ExpenseRefundCreateRequest,
    ) -> ExpenseResponse:
        async with self.unit_of_work:
            expense = await self._get_locked_expense(farm.id, expense_id)
            self._ensure_manually_managed(expense)
            if expense.canceled_at is not None:
                raise ConflictError("A cancelled expense cannot be refunded.")
            refundable = _net_payments(expense.payments)
            if request.amount.quantize(CENT) > refundable:
                raise ConflictError(
                    f"Refund exceeds the net paid amount of {refundable:.2f}."
                )
            if self.payment_repository is None:
                raise ConflictError("Expense payment records are unavailable.")
            payment = await self.payment_repository.create(
                expense.id,
                {
                    "kind": "refund",
                    "amount": request.amount.quantize(CENT),
                    "payment_date": request.payment_date,
                    "payment_method": request.payment_method,
                    "reference_number": _strip_or_none(request.reference_number),
                    "reason": request.reason.strip(),
                },
            )
            expense.payments.append(payment)
            category = await self._require_category(
                farm.id,
                expense.category,
                include_inactive=True,
            )
            await self._record_activity(
                farm,
                expense,
                "expense_payment_recorded",
                {
                    "name": expense.name,
                    "amount": str(request.amount),
                    "payment_date": request.payment_date.isoformat(),
                    "payment_method": request.payment_method.value,
                    "reason": request.reason.strip(),
                    "kind": "refund",
                    "event_action": "refund_recorded",
                },
            )
            await self.unit_of_work.commit()
            return self._to_response(expense, category.name)

    async def update_expense(
        self,
        farm: Farm,
        expense_id: UUID,
        request: ExpenseUpdateRequest,
    ) -> ExpenseResponse:
        async with self.unit_of_work:
            expense = await self._get_locked_expense(farm.id, expense_id)
            self._ensure_manually_managed(expense)
            if expense.canceled_at is not None:
                raise ConflictError("A cancelled expense cannot be edited.")
            changes = request.model_dump(exclude_unset=True)
            if "category" in changes:
                category = await self._require_category(farm.id, changes["category"])
                expense.category = category.key
            if "contact_id" in changes:
                expense.contact = await self._resolve_contact(
                    farm.id,
                    changes["contact_id"],
                )
            if "block_id" in changes:
                expense.block = await self._resolve_block(
                    farm.id,
                    changes["block_id"],
                )
            if "amount" in changes:
                paid = _net_payments(expense.payments)
                if changes["amount"].quantize(CENT) < paid:
                    raise ConflictError(
                        "Expense total cannot be lower than the amount already paid."
                    )
                expense.amount = changes["amount"].quantize(CENT)
            for field in (
                "name",
                "expense_date",
                "contact_id",
                "block_id",
                "receipt_reference",
                "notes",
            ):
                if field in changes:
                    value = changes[field]
                    setattr(
                        expense,
                        field,
                        value.strip() if field == "name" else _strip_or_none(value)
                        if field in {"receipt_reference", "notes"}
                        else value,
                    )
            category = await self._require_category(
                farm.id,
                expense.category,
                include_inactive=True,
            )
            await self._record_activity(
                farm,
                expense,
                "expense_recorded",
                {
                    "name": expense.name,
                    "category": category.name,
                    "amount": str(expense.amount),
                    "expense_date": expense.expense_date.isoformat(),
                    "event_action": "updated",
                },
            )
            await self.unit_of_work.commit()
            return self._to_response(expense, category.name)

    async def cancel_expense(
        self,
        farm: Farm,
        expense_id: UUID,
        request: ExpenseCancelRequest,
    ) -> ExpenseResponse:
        async with self.unit_of_work:
            expense = await self._get_locked_expense(farm.id, expense_id)
            self._ensure_manually_managed(expense)
            if expense.canceled_at is not None:
                raise ConflictError("This expense is already cancelled.")
            net_paid = _net_payments(expense.payments)
            if net_paid != 0:
                raise ConflictError(
                    "Reverse all payments or refunds before cancelling this expense."
                )
            expense.canceled_at = datetime.now(timezone.utc)
            expense.cancellation_reason = request.reason.strip()
            category = await self._require_category(
                farm.id,
                expense.category,
                include_inactive=True,
            )
            await self._record_activity(
                farm,
                expense,
                "expense_recorded",
                {
                    "name": expense.name,
                    "amount": str(expense.amount),
                    "category": category.name,
                    "event_action": "cancelled",
                    "cancellation_reason": expense.cancellation_reason,
                },
            )
            await self.unit_of_work.commit()
            return self._to_response(expense, category.name)

    async def list_categories(
        self,
        farm: Farm,
        *,
        include_inactive: bool = False,
    ) -> list[ExpenseCategoryResponse]:
        async with self.unit_of_work:
            categories = await self._list_categories(
                farm.id,
                include_inactive=include_inactive,
            )
            responses = [
                ExpenseCategoryResponse.model_validate(item) for item in categories
            ]
            await self.unit_of_work.commit()
            return responses

    async def create_category(
        self,
        farm: Farm,
        request: ExpenseCategoryCreateRequest,
    ) -> ExpenseCategoryResponse:
        if self.category_repository is None:
            raise ConflictError("Expense categories are unavailable.")
        name = request.name.strip()
        key = _category_key(name)
        async with self.unit_of_work:
            await self._list_categories(farm.id, include_inactive=True)
            if await self.category_repository.get_by_key(farm.id, key):
                raise ConflictError("An expense category with this name already exists.")
            category = await self.category_repository.create(
                farm.id,
                {
                    "key": key,
                    "name": name,
                    "is_default": False,
                    "is_active": True,
                },
            )
            await self.unit_of_work.commit()
            return ExpenseCategoryResponse.model_validate(category)

    async def update_category(
        self,
        farm: Farm,
        category_id: UUID,
        request: ExpenseCategoryUpdateRequest,
    ) -> ExpenseCategoryResponse:
        if self.category_repository is None:
            raise ConflictError("Expense categories are unavailable.")
        async with self.unit_of_work:
            category = await self.category_repository.get_by_id(farm.id, category_id)
            if category is None:
                raise ResourceNotFoundError("Expense category not found for this farm.")
            if request.name is not None:
                categories = await self._list_categories(
                    farm.id,
                    include_inactive=True,
                )
                if any(
                    item.id != category.id
                    and item.name.casefold() == request.name.casefold()
                    for item in categories
                ):
                    raise ConflictError(
                        "An expense category with this name already exists."
                    )
                category.name = request.name.strip()
            if request.is_active is not None:
                category.is_active = request.is_active
            await self.unit_of_work.commit()
            return ExpenseCategoryResponse.model_validate(category)

    async def _create_payment(self, expense, request: ExpensePaymentCreateRequest):
        if self.payment_repository is None:
            raise ConflictError("Expense payment records are unavailable.")
        payment = await self.payment_repository.create(
            expense.id,
            {
                "kind": "payment",
                "amount": request.amount.quantize(CENT),
                "payment_date": request.payment_date,
                "payment_method": request.payment_method,
                "reference_number": _strip_or_none(request.reference_number),
            },
        )
        expense.payments.append(payment)

    async def _get_locked_expense(self, farm_id: UUID, expense_id: UUID):
        expense = await self.expense_repository.get_by_id_for_update(
            farm_id,
            expense_id,
        )
        if expense is None:
            raise ResourceNotFoundError("Expense not found for this farm.")
        if self.payment_repository is not None:
            expense.payments = await self.payment_repository.list_by_expense(expense.id)
        return expense

    async def _resolve_contact(self, farm_id: UUID, contact_id: UUID | None):
        if contact_id is None:
            return None
        contact = await self.contact_repository.get_by_id(farm_id, contact_id)
        if contact is None:
            raise ResourceNotFoundError("Expense contact not found for this farm.")
        return contact

    async def _resolve_block(self, farm_id: UUID, block_id: UUID | None):
        if block_id is None:
            return None
        if self.block_repository is None:
            raise ConflictError("Expense block validation is unavailable.")
        block = await self.block_repository.get_by_id(farm_id, block_id)
        if block is None:
            raise ResourceNotFoundError("Expense block not found for this farm.")
        return block

    async def _require_category(
        self,
        farm_id: UUID,
        key: str,
        *,
        include_inactive: bool = False,
    ):
        if self.category_repository is None:
            raise ConflictError("Expense categories are unavailable.")
        categories = await self._list_categories(farm_id, include_inactive=True)
        category = next((item for item in categories if item.key == key), None)
        if category is None or (not include_inactive and not category.is_active):
            raise ResourceNotFoundError("Expense category not found for this farm.")
        return category

    @staticmethod
    def _ensure_manually_managed(expense) -> None:
        if expense.purchase_transaction_id is not None:
            raise ConflictError(
                "This expense is linked to a purchase. Manage its details and payments "
                "from the purchase transaction."
            )

    async def _list_categories(self, farm_id: UUID, *, include_inactive: bool):
        if self.category_repository is None:
            raise ConflictError("Expense categories are unavailable.")
        categories = await self.category_repository.list_by_farm(
            farm_id,
            include_inactive=True,
        )
        existing_keys = {category.key for category in categories}
        for key, name in DEFAULT_EXPENSE_CATEGORIES:
            if key not in existing_keys:
                categories.append(
                    await self.category_repository.create(
                        farm_id,
                        {
                            "key": key,
                            "name": name,
                            "is_default": True,
                            "is_active": True,
                        },
                    )
                )
        return (
            categories
            if include_inactive
            else [category for category in categories if category.is_active]
        )

    async def _record_activity(
        self,
        farm: Farm,
        expense,
        activity_type: str,
        details: dict,
    ) -> None:
        await self.activity_service.record(
            farm_id=farm.id,
            user_id=farm.owner_id,
            activity_type=ActivityType.EXPENSE_RECORDED,
            entity_type=ActivityEntityType.EXPENSE,
            entity_id=expense.id,
            details={"event_action": activity_type} | details,
        )

    @staticmethod
    def _to_response(expense, category_name: str) -> ExpenseResponse:
        paid = _net_payments(expense.payments)
        balance = max(Decimal("0.00"), expense.amount - paid)
        return ExpenseResponse(
            id=expense.id,
            farm_id=expense.farm_id,
            name=expense.name,
            category=expense.category,
            category_name=category_name,
            amount=expense.amount,
            amount_paid=paid,
            balance_due=balance,
            payment_status=_payment_status(
                expense.amount,
                paid,
                expense.canceled_at,
            ),
            expense_date=expense.expense_date,
            contact_id=expense.contact_id,
            contact_name=expense.contact.name if expense.contact else None,
            block_id=expense.block_id,
            block_name=expense.block.name if expense.block else None,
            purchase_transaction_id=expense.purchase_transaction_id,
            purchase_reference=(
                expense.purchase_transaction.reference_number
                if expense.purchase_transaction
                else None
            ),
            receipt_reference=expense.receipt_reference,
            notes=expense.notes,
            payments=[
                ExpensePaymentResponse.model_validate(payment, from_attributes=True)
                for payment in expense.payments
            ],
            canceled_at=expense.canceled_at,
            cancellation_reason=expense.cancellation_reason,
            created_at=expense.created_at,
            updated_at=expense.updated_at,
        )


def _net_payments(payments) -> Decimal:
    return sum(
        (
            payment.amount if payment.kind == "payment" else -payment.amount
            for payment in payments
        ),
        Decimal("0.00"),
    )


def _payment_status(amount: Decimal, paid: Decimal, canceled_at) -> str:
    if canceled_at is not None:
        return "cancelled"
    if paid >= amount:
        return "paid"
    return "partial" if paid > 0 else "unpaid"


def _strip_or_none(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _category_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    if not key:
        raise ConflictError("Enter a meaningful expense category name.")
    return key[:80]

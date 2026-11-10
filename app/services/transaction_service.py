from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.transactions import Transaction
from app.repositories.contact_repository import ContactRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.transaction_reference_counter_repository import (
    TransactionReferenceCounterRepository,
)
from app.repositories.farm_settings_repository import FarmSettingsRepository
from app.repositories.transaction_item_repository import TransactionItemRepository
from app.repositories.transaction_payment_repository import TransactionPaymentRepository
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_replacement_repository import (
    PurchaseReplacementRepository,
)
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.repositories.expense_repository import ExpenseRepository
from app.repositories.expense_payment_repository import ExpensePaymentRepository
from app.repositories.expense_category_repository import ExpenseCategoryRepository
from app.services.activity_service import ActivityService
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenType,
    ContactRoleEnum,
    ProductType,
    TransactionStatus,
    TransactionType,
    NotificationEventType,
    InventoryMovementType,
    PaymentMethod,
)
from app.schemas.payment import PaymentCreate, PaymentRecordResponse, PaymentResponse
from app.schemas.transaction import (
    TransactionCreate,
    TransactionItemResponse,
    TransactionResponse,
)
from app.services.transaction_balance import (
    calculate_transaction_balance,
    get_settlement_adjustment,
)
from app.services.inventory_service import InventoryService
from app.services.transaction_pricing import (
    calculate_discount_allocation,
    calculate_sale_return_credit_total,
)
from app.services.transaction_reference import (
    farm_local_date,
    format_transaction_reference,
)

app_logger = get_application_logger()


_FOREIGN_KEY_MESSAGES = {
    "transactions_farm_id_fkey": "Farm not found.",
    "transactions_contact_id_fkey": "Contact not found.",
    "transaction_items_product_id_fkey": "Product not found.",
    "transaction_items_unit_id_fkey": "Unit not found.",
    "transaction_payments_transaction_id_fkey": "Purchase transaction not found.",
}


def _get_foreign_key_violation(error: IntegrityError) -> tuple[bool, str | None]:
    original_error = error.orig
    while original_error is not None:
        is_foreign_key_violation = (
            getattr(original_error, "sqlstate", None) == "23503"
            or getattr(original_error, "pgcode", None) == "23503"
            or "FOREIGN KEY constraint failed" in str(original_error)
        )
        if is_foreign_key_violation:
            diagnostic = getattr(original_error, "diag", None)
            constraint_name = getattr(diagnostic, "constraint_name", None)
            return True, constraint_name
        original_error = original_error.__cause__ or original_error.__context__
    return False, None


class TransactionService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        transaction_item_repository: TransactionItemRepository,
        transaction_payment_repository: TransactionPaymentRepository,
        contact_repository: ContactRepository,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        sale_return_repository: SaleReturnRepository,
        transaction_refund_repository: TransactionRefundRepository,
        purchase_supplier_refund_repository: PurchaseSupplierRefundRepository | None = None,
        notification_outbox_repository: NotificationOutboxRepository | None = None,
        farm_settings_repository: FarmSettingsRepository | None = None,
        transaction_reference_counter_repository: TransactionReferenceCounterRepository | None = None,
        inventory_service: InventoryService | None = None,
        purchase_return_repository: PurchaseReturnRepository | None = None,
        purchase_replacement_repository: PurchaseReplacementRepository | None = None,
        expense_repository: ExpenseRepository | None = None,
        expense_payment_repository: ExpensePaymentRepository | None = None,
        expense_category_repository: ExpenseCategoryRepository | None = None,
    ):
        self.transaction_repository = transaction_repository
        self.transaction_item_repository = transaction_item_repository
        self.transaction_payment_repository = transaction_payment_repository
        self.contact_repository = contact_repository
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.sale_return_repository = sale_return_repository
        self.transaction_refund_repository = transaction_refund_repository
        self.purchase_supplier_refund_repository = purchase_supplier_refund_repository
        self.notification_outbox_repository = notification_outbox_repository
        self.farm_settings_repository = farm_settings_repository
        self.transaction_reference_counter_repository = (
            transaction_reference_counter_repository
        )
        self.inventory_service = inventory_service
        self.purchase_return_repository = purchase_return_repository
        self.purchase_replacement_repository = purchase_replacement_repository
        self.expense_repository = expense_repository
        self.expense_payment_repository = expense_payment_repository
        self.expense_category_repository = expense_category_repository

    async def record_payment(
        self,
        farm_id: UUID,
        transaction_id: UUID,
        payment_data: PaymentCreate,
        user_id: UUID | None = None,
    ) -> PaymentRecordResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Transaction not found for this farm.")
            if transaction.transaction_type not in {TransactionType.PURCHASE, TransactionType.SALE}:
                raise ConflictError(
                    "Payments can only be recorded against purchase or sale transactions."
                )
            if transaction.status == TransactionStatus.CANCELLED:
                raise ConflictError("A cancelled transaction cannot accept payments.")

            payment = await self.transaction_payment_repository.create(
                {
                    "transaction_id": transaction.id,
                    **payment_data.model_dump(exclude_none=True),
                }
            )
            await self._sync_purchase_expense_payment(transaction, payment)
            payments = await self.transaction_payment_repository.list_by_transaction(
                transaction.id
            )
            amount_paid = sum(
                (recorded_payment.amount for recorded_payment in payments),
                Decimal("0.00"),
            )
            transaction_total = sum(
                (item.total_amount for item in transaction.items),
                Decimal("0.00"),
            )
            if transaction.transaction_type == TransactionType.SALE:
                amount_refunded = (
                    await self.transaction_refund_repository.get_total_by_transaction(
                        transaction.id
                    )
                )
                returned_quantities = (
                    await self.sale_return_repository.get_credited_quantities_by_item(
                        transaction.id
                    )
                )
                total_credits = calculate_sale_return_credit_total(
                    transaction.items,
                    returned_quantities,
                )
            else:
                amount_refunded = (
                    await self.purchase_supplier_refund_repository.get_total_by_transaction(
                        transaction.id
                    )
                    if self.purchase_supplier_refund_repository is not None
                    else Decimal("0.00")
                )
                total_credits = (
                    await self.purchase_return_repository.get_total_credit_by_transaction(
                        transaction.id
                    )
                    if self.purchase_return_repository is not None
                    else Decimal("0.00")
                )
                replacement_credits = (
                    await self.purchase_replacement_repository.get_total_credit_applied_by_transaction(
                        transaction.id
                    )
                    if self.purchase_replacement_repository is not None
                    else Decimal("0.00")
                )
                settlement_adjustment = (
                    get_settlement_adjustment(transaction) - replacement_credits
                )
            if transaction.transaction_type == TransactionType.SALE:
                settlement_adjustment = get_settlement_adjustment(transaction)
            balances = calculate_transaction_balance(
                transaction_total,
                amount_paid,
                amount_refunded,
                total_credits,
                settlement_adjustment=settlement_adjustment,
            )
            contact = (
                await self.contact_repository.get_by_id(
                    farm_id,
                    transaction.contact_id,
                )
                if transaction.contact_id is not None
                else None
            )
            if (
                transaction.transaction_type == TransactionType.SALE
                and (
                    balances.balance_due > Decimal("0.00")
                    or balances.credit_balance > Decimal("0.00")
                )
                and (contact is None or not contact.name.strip())
            ):
                raise ConflictError(
                    "A customer with a name is required to track a sale balance or credit."
                )
            if (
                transaction.transaction_type == TransactionType.SALE
                and (
                    balances.balance_due > Decimal("0.00")
                    or balances.credit_balance > Decimal("0.00")
                )
                and contact is not None
                and not any(
                    role.role == ContactRoleEnum.CUSTOMER
                    for role in contact.contact_roles
                )
            ):
                raise ConflictError("The linked sale contact is not a customer.")
            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.TRANSACTION_PAYMENT_RECORDED,
                entity_type=ActivityEntityType.TRANSACTION_PAYMENT,
                entity_id=payment.id,
                details={
                    "transaction_id": str(transaction.id),
                    "transaction_type": transaction.transaction_type.value,
                    "reference_number": transaction.reference_number,
                    "contact_name": contact.name if contact is not None else None,
                    "amount": str(payment.amount),
                    "payment_date": payment.payment_date.isoformat(),
                    "payment_time": (
                        payment.payment_time.isoformat()
                        if payment.payment_time is not None
                        else None
                    ),
                    "payment_method": payment.payment_method.value,
                    "payment_reference": payment.reference_number,
                    "notes": payment.notes,
                    "transaction_total": str(transaction_total),
                    "amount_paid": str(amount_paid),
                    "balance_due": str(balances.balance_due),
                    "credit_balance": str(balances.credit_balance),
                },
            )
            if self.notification_outbox_repository is not None:
                payment_farm_settings = (
                    await self.farm_settings_repository.get_farm_settings(farm_id)
                    if self.farm_settings_repository is not None
                    else None
                )
                await self.notification_outbox_repository.enqueue(
                    farm_id=farm_id,
                    event_type=NotificationEventType.PAYMENT_RECORDED.value,
                    payload={
                        "transaction_id": str(transaction.id),
                        "payment_id": str(payment.id),
                        "payment_amount": str(payment.amount),
                        "transaction_type": transaction.transaction_type.value,
                        "reference_number": transaction.reference_number,
                        "currency": (
                            payment_farm_settings.currency
                            if payment_farm_settings is not None
                            else None
                        ),
                    },
                    dedupe_key=f"payment.recorded:{payment.id}",
                )
            await self.unit_of_work.commit()
            app_logger.info(
                "transaction_payment_recorded",
                extra={
                    "event": "transaction_payment_recorded",
                    "farm_id": farm_id,
                    "user_id": user_id,
                    "transaction_id": transaction.id,
                },
            )
            return PaymentRecordResponse(
                payment=PaymentResponse.model_validate(payment),
                amount_paid=balances.amount_paid,
                balance_due=balances.balance_due,
                credit_balance=balances.credit_balance,
            )

    async def create_transaction(
        self,
        farm_id: UUID,
        transaction_data: TransactionCreate,
        user_id: UUID | None = None,
        *,
        commit: bool = True,
    ) -> TransactionResponse:
        try:
            async with self.unit_of_work:
                if (
                    self.farm_settings_repository is None
                    or self.transaction_reference_counter_repository is None
                ):
                    raise RuntimeError(
                        "Transaction reference generation is not configured."
                    )

                farm_settings = await self.farm_settings_repository.get_farm_settings(
                    farm_id
                )
                transaction_date = transaction_data.transaction_date or farm_local_date(
                    farm_settings.timezone if farm_settings else None
                )
                sequence_number = (
                    await self.transaction_reference_counter_repository.allocate_next_number(
                        farm_id,
                        transaction_data.transaction_type.value,
                        transaction_date,
                    )
                )
                reference_number = format_transaction_reference(
                    transaction_data.transaction_type,
                    transaction_date,
                    sequence_number,
                )

                contact = None
                if transaction_data.contact_id is not None:
                    contact = await self.contact_repository.get_by_id(
                        farm_id,
                        transaction_data.contact_id,
                    )
                    if contact is None:
                        raise ResourceNotFoundError("Contact not found for this farm.")
                    if (
                        transaction_data.transaction_type == TransactionType.PURCHASE
                        and not any(
                            role.role == ContactRoleEnum.SUPPLIER
                            for role in contact.contact_roles
                        )
                    ):
                        raise ConflictError("The selected contact is not a supplier.")
                    if (
                        transaction_data.transaction_type == TransactionType.SALE
                        and not any(
                            role.role == ContactRoleEnum.CUSTOMER
                            for role in contact.contact_roles
                        )
                    ):
                        raise ConflictError("The selected contact is not a customer.")

                transaction_fields = transaction_data.model_dump(
                    exclude_none=True,
                    exclude={"items", "payments"},
                )
                if (
                    transaction_data.discount_type is not None
                    and transaction_data.transaction_type
                    not in {TransactionType.PURCHASE, TransactionType.SALE}
                ):
                    raise ConflictError(
                        "Discounts can only be applied to purchase or sale transactions."
                    )
                line_subtotals = [
                    (item.quantity * item.unit_price).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    for item in transaction_data.items
                ]
                try:
                    discount_amount, item_discounts = calculate_discount_allocation(
                        line_subtotals,
                        transaction_data.discount_type,
                        transaction_data.discount_value,
                    )
                except ValueError as exc:
                    raise ConflictError(str(exc)) from exc
                if transaction_data.transaction_type == TransactionType.SALE:
                    sale_total = sum(line_subtotals, Decimal("0.00")) - discount_amount
                    initial_paid = sum(
                        (payment.amount for payment in transaction_data.payments),
                        Decimal("0.00"),
                    )
                    if (
                        sale_total != initial_paid
                        and (contact is None or not contact.name.strip())
                    ):
                        raise ConflictError(
                            "A customer with a name is required to track a sale balance or credit."
                        )
                transaction_fields["discount_amount"] = discount_amount
                transaction_fields["transaction_date"] = transaction_date
                transaction_fields["reference_number"] = reference_number
                transaction = await self.transaction_repository.create(
                    farm_id,
                    transaction_fields,
                )
                item_models = []
                item_summaries = []
                activity_items: list[dict[str, object]] = []
                expense_items: list[tuple[str, ProductType, Decimal]] = []
                transaction_total = Decimal("0.00")
                for item_index, item in enumerate(transaction_data.items):
                    product = await self.product_repository.get_by_id_for_update(
                        farm_id,
                        item.product_id,
                    )
                    if product is None:
                        raise ResourceNotFoundError("Product not found for this farm.")
                    if not product.is_active:
                        if transaction_data.transaction_type == TransactionType.SALE:
                            raise ConflictError("Inactive products cannot be sold.")
                        raise ConflictError("Inactive products cannot be purchased.")
                    if (
                        transaction_data.transaction_type == TransactionType.SALE
                        and not product.is_sellable
                    ):
                        raise ConflictError(
                            "This product is not marked as available for sale."
                        )
                    item_summaries.append(f"{item.quantity:g} × {product.name}")

                    product_unit = await self.product_unit_repository.get_by_product_and_unit(
                        product.id,
                        item.unit_id,
                    )
                    if product_unit is None:
                        raise ConflictError("The selected unit is not valid for this product.")

                    conversion_factor = product_unit.conversion_factor
                    ordered_base_quantity = item.quantity * conversion_factor
                    if product.product_type == ProductType.CHICKENS:
                        if item.chicken_type is None:
                            raise ConflictError(
                                "Chicken purchases require a chicken type for each item."
                            )
                        if ordered_base_quantity != ordered_base_quantity.to_integral_value():
                            raise ConflictError(
                                "Chicken purchase quantity must convert to a whole number of chickens."
                            )
                    elif item.chicken_type is not None:
                        raise ConflictError(
                            "Chicken type can only be set for chicken products."
                        )

                    item_subtotal = line_subtotals[item_index]
                    item_discount = item_discounts[item_index]
                    item_total = item_subtotal - item_discount
                    transaction_total += item_total
                    if (
                        transaction_data.transaction_type == TransactionType.PURCHASE
                        and product.product_type
                        not in {ProductType.CHICKENS, ProductType.EGGS}
                    ):
                        expense_items.append((product.name, product.product_type, item_total))
                    item_model = await self.transaction_item_repository.create(
                        {
                            "transaction_id": transaction.id,
                            **item.model_dump(exclude_none=True, exclude={"batch_allocations"}),
                            "conversion_factor": conversion_factor,
                            "subtotal_amount": item_subtotal,
                            "discount_amount": item_discount,
                            "total_amount": item_total,
                        }
                    )
                    item_models.append(
                        (item_model, ordered_base_quantity, product.product_type)
                    )
                    if (
                        self.inventory_service is not None
                        and transaction_data.status == TransactionStatus.COMPLETED
                        and product.product_type != ProductType.CHICKENS
                        and not (
                            transaction_data.transaction_type
                            == TransactionType.SALE
                            and transaction_data.fulfillment_required
                            and product.product_type == ProductType.EGGS
                        )
                    ):
                        is_purchase = (
                            transaction_data.transaction_type
                            == TransactionType.PURCHASE
                        )
                        await self.inventory_service.append_movement(
                            farm_id=farm_id,
                            user_id=user_id,
                            product_id=product.id,
                            quantity_delta=(
                                ordered_base_quantity
                                if is_purchase
                                else -ordered_base_quantity
                            ),
                            movement_type=(
                                InventoryMovementType.RECEIPT
                                if is_purchase
                                else InventoryMovementType.SALE
                            ),
                            occurred_on=transaction_date,
                            notes=(
                                f"{'Purchase' if is_purchase else 'Sale'} "
                                f"{transaction.reference_number}"
                            ),
                            source_type="transaction",
                            source_id=transaction.id,
                            source_item_id=item_model.id,
                            unit_cost=(
                                item_total / ordered_base_quantity
                                if is_purchase and ordered_base_quantity > 0
                                else None
                            ),
                        )
                    activity_items.append(
                        {
                            "product_name": product.name,
                            "quantity": str(item.quantity),
                            "unit_id": str(item.unit_id),
                            "unit_name": product_unit.unit.name,
                            "unit_abbreviation": product_unit.unit.abbreviation,
                            "unit_price": str(item.unit_price),
                            "subtotal": str(item_subtotal),
                            "discount": str(item_discount),
                            "total": str(item_total),
                            "chicken_type": (
                                item.chicken_type.value
                                if item.chicken_type is not None
                                else None
                            ),
                            "notes": item.notes,
                        }
                    )

                payment_models = []
                for payment in transaction_data.payments:
                    payment_model = await self.transaction_payment_repository.create(
                        {
                            "transaction_id": transaction.id,
                            **payment.model_dump(exclude_none=True),
                        }
                    )
                    payment_models.append(payment_model)
                await self._record_purchase_expense(
                    farm_id=farm_id,
                    user_id=user_id,
                    transaction=transaction,
                    contact=contact,
                    transaction_data=transaction_data,
                    expense_items=expense_items,
                    payments=payment_models,
                )
                await self.activity_service.record(
                    farm_id=farm_id,
                    user_id=user_id,
                    activity_type=ActivityType.TRANSACTION_CREATED,
                    entity_type=ActivityEntityType.TRANSACTION,
                    entity_id=transaction.id,
                    details={
                        "transaction_type": transaction.transaction_type.value,
                        "reference_number": transaction.reference_number,
                        "transaction_date": transaction.transaction_date.isoformat(),
                        "transaction_time": (
                            transaction.transaction_time.isoformat()
                            if transaction.transaction_time is not None
                            else None
                        ),
                        "contact_name": contact.name if contact is not None else None,
                        "transaction_total": str(transaction_total),
                        "amount_paid": str(
                            sum(
                                (payment.amount for payment in payment_models),
                                Decimal("0.00"),
                            )
                        ),
                        "discount_type": transaction.discount_type,
                        "discount_value": str(transaction.discount_value),
                        "discount_amount": str(transaction.discount_amount),
                        "discount_reason": transaction.discount_reason,
                        "notes": transaction.notes,
                        "item_count": len(item_models),
                        "initial_payment_count": len(payment_models),
                        "items": activity_items,
                    },
                )
                if self.notification_outbox_repository is not None:
                    contact = (
                        await self.contact_repository.get_by_id(
                            farm_id,
                            transaction.contact_id,
                        )
                        if transaction.contact_id is not None
                        else None
                    )
                    farm_settings = (
                        await self.farm_settings_repository.get_farm_settings(farm_id)
                        if self.farm_settings_repository is not None
                        else None
                    )
                    event_type = (
                        NotificationEventType.SALE_RECORDED
                        if transaction.transaction_type == TransactionType.SALE
                        else NotificationEventType.PURCHASE_RECORDED
                    )
                    await self.notification_outbox_repository.enqueue(
                        farm_id=farm_id,
                        event_type=event_type.value,
                        payload={
                            "transaction_id": str(transaction.id),
                            "transaction_type": transaction.transaction_type.value,
                            "reference_number": transaction.reference_number,
                            "transaction_total": str(transaction_total),
                            "items_summary": ", ".join(item_summaries[:3])
                            + (
                                f" + {len(item_summaries) - 3} more"
                                if len(item_summaries) > 3
                                else ""
                            ),
                            "contact_name": contact.name if contact is not None else None,
                            "currency": (
                                farm_settings.currency
                                if farm_settings is not None
                                else None
                            ),
                        },
                        dedupe_key=f"transaction.recorded:{transaction.id}",
                    )
                if commit:
                    await self.unit_of_work.commit()

                amount_paid = sum(
                    (payment.amount for payment in payment_models),
                    Decimal("0.00"),
                )
                response_items = [
                    TransactionItemResponse(
                        id=item_model.id,
                        product_id=item_model.product_id,
                        unit_id=item_model.unit_id,
                        quantity=item_model.quantity,
                        conversion_factor=item_model.conversion_factor,
                        ordered_base_quantity=ordered_base_quantity,
                        chicken_type=item_model.chicken_type,
                        product_type=product_type,
                        unit_price=item_model.unit_price,
                        subtotal_amount=item_model.subtotal_amount,
                        discount_amount=item_model.discount_amount,
                        total_amount=item_model.total_amount,
                        notes=item_model.notes,
                        quantity_received=Decimal("0"),
                        quantity_remaining=ordered_base_quantity,
                    )
                    for item_model, ordered_base_quantity, product_type in item_models
                ]
                response = TransactionResponse(
                    id=transaction.id,
                    farm_id=transaction.farm_id,
                    contact_id=transaction.contact_id,
                    transaction_type=transaction.transaction_type,
                    status=transaction.status,
                    transaction_date=transaction.transaction_date,
                    transaction_time=transaction_data.transaction_time,
                    reference_number=transaction.reference_number,
                    notes=transaction.notes,
                    discount_type=transaction_data.discount_type,
                    discount_value=transaction_data.discount_value,
                    discount_amount=discount_amount,
                    discount_reason=transaction_data.discount_reason,
                    items=response_items,
                    payments=payment_models,
                    transaction_total=transaction_total,
                    amount_paid=amount_paid,
                    balance_due=max(transaction_total - amount_paid, Decimal("0.00")),
                    credit_balance=max(amount_paid - transaction_total, Decimal("0.00")),
                    created_at=transaction.created_at,
                    updated_at=transaction.updated_at,
                )
                app_logger.info(
                    "transaction_created",
                    extra={
                        "event": "transaction_created",
                        "farm_id": farm_id,
                        "user_id": user_id,
                        "transaction_id": transaction.id,
                        "item_count": len(transaction_data.items),
                        "payment_count": len(transaction_data.payments),
                        "transaction_total": str(transaction_total),
                    },
                )
                return response
        except IntegrityError as exc:
            is_foreign_key_violation, constraint_name = _get_foreign_key_violation(exc)
            if is_foreign_key_violation:
                message = "A referenced record for this transaction was not found."
                message = _FOREIGN_KEY_MESSAGES.get(constraint_name or "", message)
                raise ResourceNotFoundError(
                    message
                ) from exc
            raise

    async def _record_purchase_expense(
        self,
        *,
        farm_id: UUID,
        user_id: UUID | None,
        transaction,
        contact,
        transaction_data: TransactionCreate,
        expense_items: list[tuple[str, ProductType, Decimal]],
        payments: list,
    ) -> None:
        if (
            transaction_data.transaction_type != TransactionType.PURCHASE
            or transaction_data.status != TransactionStatus.COMPLETED
            or not expense_items
            or self.expense_repository is None
            or self.expense_payment_repository is None
            or self.expense_category_repository is None
        ):
            return

        expense_amount = sum((item[2] for item in expense_items), Decimal("0.00"))
        if expense_amount <= 0:
            return

        category_by_type = {
            ProductType.FEED: ("feed_and_nutrition", "Feed and nutrition"),
            ProductType.MEDICATION: (
                "medication_veterinary",
                "Medication and veterinary",
            ),
            ProductType.EQUIPMENT: ("equipment", "Equipment"),
            ProductType.OTHER: ("other", "Other"),
        }
        item_types = {item[1] for item in expense_items}
        category_key, category_name = (
            category_by_type[next(iter(item_types))]
            if len(item_types) == 1
            else ("other", "Other")
        )
        if await self.expense_category_repository.get_by_key(farm_id, category_key) is None:
            await self.expense_category_repository.create(
                farm_id,
                {
                    "key": category_key,
                    "name": category_name,
                    "is_default": True,
                    "is_active": True,
                },
            )

        product_names = ", ".join(dict.fromkeys(item[0] for item in expense_items))
        notes = transaction_data.notes
        purchase_detail = f"Purchased products: {product_names}"
        notes = f"{notes.strip()}\n{purchase_detail}" if notes else purchase_detail
        latest_payment = payments[-1] if payments else None
        expense = await self.expense_repository.create(
            farm_id,
            {
                "name": product_names,
                "category": category_key,
                "amount": expense_amount,
                "expense_date": transaction.transaction_date,
                "contact_id": transaction.contact_id,
                "payment_method": (
                    latest_payment.payment_method
                    if latest_payment is not None
                    else PaymentMethod.CASH
                ),
                "reference_number": (
                    latest_payment.reference_number
                    if latest_payment is not None
                    else None
                ),
                "notes": notes,
                "purchase_transaction_id": transaction.id,
                "purchase_transaction": transaction,
            },
        )
        for payment in payments:
            await self._append_purchase_expense_payment(expense, payment)
        await self.activity_service.record(
            farm_id=farm_id,
            user_id=user_id,
            activity_type=ActivityType.EXPENSE_RECORDED,
            entity_type=ActivityEntityType.EXPENSE,
            entity_id=expense.id,
            details={
                "event_action": "inventory_purchase_recorded",
                "name": expense.name,
                "expense_name": expense.name,
                "product_names": product_names,
                "category": category_name,
                "amount": str(expense.amount),
                "expense_date": expense.expense_date.isoformat(),
                "transaction_id": str(transaction.id),
                "transaction_reference": transaction.reference_number,
                "contact_name": contact.name if contact else None,
                "item_count": len(expense_items),
            },
        )

    async def _sync_purchase_expense_payment(self, transaction, payment) -> None:
        if (
            transaction.transaction_type != TransactionType.PURCHASE
            or self.expense_repository is None
            or self.expense_payment_repository is None
        ):
            return
        expense = await self.expense_repository.get_by_purchase_transaction(
            transaction.id
        )
        if expense is not None:
            await self._append_purchase_expense_payment(expense, payment)

    async def _append_purchase_expense_payment(self, expense, payment) -> None:
        if self.expense_payment_repository is None:
            return
        paid = sum(
            (
                entry.amount if entry.kind == "payment" else -entry.amount
                for entry in expense.payments
            ),
            Decimal("0.00"),
        )
        remaining = max(expense.amount - paid, Decimal("0.00"))
        amount = min(payment.amount, remaining)
        if amount <= 0:
            return
        expense_payment = await self.expense_payment_repository.create(
            expense.id,
            {
                "purchase_payment_id": payment.id,
                "kind": "payment",
                "amount": amount,
                "payment_date": payment.payment_date,
                "payment_method": payment.payment_method,
                "reference_number": payment.reference_number,
            },
        )
        expense.payments.append(expense_payment)
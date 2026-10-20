from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.repositories.purchase_replacement_repository import PurchaseReplacementRepository
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.transaction_payment_repository import TransactionPaymentRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    TransactionStatus,
    TransactionType,
)
from app.schemas.purchase_supplier_refund import (
    PurchaseSupplierRefundCreateRequest,
    PurchaseSupplierRefundRecordResponse,
    PurchaseSupplierRefundResponse,
)
from app.services.activity_service import ActivityService
from app.services.transaction_balance import (
    calculate_transaction_balance,
    get_settlement_adjustment,
)

logger = get_application_logger()


class PurchaseSupplierRefundService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        payment_repository: TransactionPaymentRepository,
        purchase_return_repository: PurchaseReturnRepository,
        supplier_refund_repository: PurchaseSupplierRefundRepository,
        replacement_repository: PurchaseReplacementRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.payment_repository = payment_repository
        self.purchase_return_repository = purchase_return_repository
        self.supplier_refund_repository = supplier_refund_repository
        self.replacement_repository = replacement_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service

    async def create_refund(
        self,
        farm_id: UUID,
        transaction_id: UUID,
        request: PurchaseSupplierRefundCreateRequest,
        user_id: UUID | None = None,
    ) -> PurchaseSupplierRefundRecordResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Purchase transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.PURCHASE:
                raise ConflictError("Supplier refunds can only be recorded for purchases.")
            if transaction.status == TransactionStatus.CANCELLED:
                raise ConflictError("A cancelled purchase cannot receive supplier refunds.")

            return_item = await self.purchase_return_repository.get_return_item(
                transaction_id,
                request.purchase_return_item_id,
            )
            if return_item is None:
                raise ResourceNotFoundError(
                    "Purchase return item was not found on this transaction."
                )

            previously_refunded = (
                await self.supplier_refund_repository.get_total_by_return_item(
                    return_item.id
                )
            )
            replacement_credit = (
                await self.replacement_repository.get_credit_applied_by_return_item(
                    return_item.id
                )
            )
            item_credit_remaining = max(
                return_item.credit_amount - previously_refunded - replacement_credit,
                Decimal("0.00"),
            )
            if request.amount > item_credit_remaining:
                raise ConflictError(
                    f"Refund exceeds this return item's unsettled credit of "
                    f"{item_credit_remaining}."
                )

            payments = await self.payment_repository.list_by_transaction(transaction_id)
            amount_received = sum(
                (payment.amount for payment in payments),
                Decimal("0.00"),
            )
            transaction_refunded = (
                await self.supplier_refund_repository.get_total_by_transaction(
                    transaction_id
                )
            )
            transaction_total = sum(
                (item.total_amount for item in transaction.items),
                Decimal("0.00"),
            )
            purchase_return_credit = (
                await self.purchase_return_repository.get_total_credit_by_transaction(
                    transaction_id
                )
            )
            replacement_credit = (
                await self.replacement_repository.get_total_credit_applied_by_transaction(
                    transaction_id
                )
            )
            balances_before_refund = calculate_transaction_balance(
                transaction_total,
                amount_received,
                transaction_refunded,
                purchase_return_credit,
                settlement_adjustment=(
                    get_settlement_adjustment(transaction) - replacement_credit
                ),
            )
            if request.amount > balances_before_refund.credit_balance:
                raise ConflictError(
                    f"Supplier refund exceeds the transaction's available credit of "
                    f"{balances_before_refund.credit_balance}."
                )
            refundable_cash = max(amount_received - transaction_refunded, Decimal("0.00"))
            if request.amount > refundable_cash:
                raise ConflictError(
                    f"Supplier cash refund exceeds the purchase payments not yet returned: "
                    f"{refundable_cash}. Use the remaining supplier credit for replacement chickens."
                )

            refund = await self.supplier_refund_repository.create(
                {
                    "transaction_id": transaction_id,
                    **request.model_dump(exclude_none=True),
                }
            )
            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.PURCHASE_SUPPLIER_REFUND_RECORDED,
                entity_type=ActivityEntityType.PURCHASE_SUPPLIER_REFUND,
                entity_id=refund.id,
                details={
                    "transaction_id": str(transaction_id),
                    "transaction_type": transaction.transaction_type.value,
                    "transaction_reference_number": transaction.reference_number,
                    "purchase_return_item_id": str(return_item.id),
                    "amount": str(refund.amount),
                    "payment_method": refund.payment_method.value,
                    "refund_date": refund.refund_date.isoformat(),
                    "reference_number": refund.reference_number,
                    "reason": refund.reason,
                    "notes": refund.notes,
                },
            )

            total_refunds = transaction_refunded + refund.amount
            balances = calculate_transaction_balance(
                transaction_total,
                amount_received,
                total_refunds,
                purchase_return_credit,
                settlement_adjustment=(
                    get_settlement_adjustment(transaction) - replacement_credit
                ),
            )
            return_credit_remaining = await self._return_credit_remaining(
                transaction_id,
                balances.credit_balance,
            )
            await self.unit_of_work.commit()
            logger.info(
                "purchase_supplier_refund_recorded",
                extra={
                    "event": "purchase_supplier_refund_recorded",
                    "farm_id": farm_id,
                    "user_id": user_id,
                    "transaction_id": transaction_id,
                    "refund_id": refund.id,
                    "amount": str(refund.amount),
                    "payment_method": refund.payment_method.value,
                },
            )
            return PurchaseSupplierRefundRecordResponse(
                refund=PurchaseSupplierRefundResponse.model_validate(refund),
                return_credit_remaining=return_credit_remaining,
                adjusted_transaction_total=balances.adjusted_transaction_total,
                amount_paid=balances.amount_paid,
                balance_due=balances.balance_due,
                credit_balance=balances.credit_balance,
            )

    async def list_refunds(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[PurchaseSupplierRefundResponse]:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Purchase transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.PURCHASE:
                raise ConflictError("Supplier refund history is only available for purchases.")
            refunds = await self.supplier_refund_repository.list_by_transaction(
                transaction_id
            )
            return [
                PurchaseSupplierRefundResponse.model_validate(refund)
                for refund in refunds
            ]

    async def _return_credit_remaining(
        self,
        transaction_id: UUID,
        available_credit: Decimal,
    ) -> Decimal:
        credit = await self.purchase_return_repository.get_total_credit_by_transaction(
            transaction_id
        )
        refunds = await self.supplier_refund_repository.get_total_by_transaction(
            transaction_id
        )
        replacement_credit = (
            await self.replacement_repository.get_total_credit_applied_by_transaction(
                transaction_id
            )
        )
        unspent_return_credit = max(
            credit - refunds - replacement_credit,
            Decimal("0.00"),
        )
        return min(unspent_return_credit, available_credit)
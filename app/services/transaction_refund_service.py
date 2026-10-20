from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_payment_repository import TransactionPaymentRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    TransactionType,
)
from app.schemas.transaction_refund import (
    TransactionRefundCreateRequest,
    TransactionRefundRecordResponse,
    TransactionRefundResponse,
)
from app.services.activity_service import ActivityService
from app.services.transaction_balance import (
    calculate_transaction_balance,
    get_settlement_adjustment,
)

logger = get_application_logger()


class TransactionRefundService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        transaction_payment_repository: TransactionPaymentRepository,
        transaction_refund_repository: TransactionRefundRepository,
        sale_return_repository: SaleReturnRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
    ) -> None:
        self.transaction_repository = transaction_repository
        self.transaction_payment_repository = transaction_payment_repository
        self.transaction_refund_repository = transaction_refund_repository
        self.sale_return_repository = sale_return_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service

    async def create_refund(
        self,
        farm_id: UUID,
        transaction_id: UUID,
        request: TransactionRefundCreateRequest,
        user_id: UUID | None = None,
    ) -> TransactionRefundRecordResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id_for_update(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.SALE:
                raise ConflictError("Refunds can only be issued for sale transactions.")

            payments = await self.transaction_payment_repository.list_by_transaction(
                transaction_id
            )
            amount_received = sum(
                (payment.amount for payment in payments),
                Decimal("0.00"),
            )
            amount_refunded = (
                await self.transaction_refund_repository.get_total_by_transaction(
                    transaction_id
                )
            )
            total_credits = (
                await self.sale_return_repository.get_total_credit_by_transaction(
                    transaction_id
                )
            )
            transaction_total = sum(
                (item.total_amount for item in transaction.items),
                Decimal("0.00"),
            )
            current_balances = calculate_transaction_balance(
                transaction_total,
                amount_received,
                amount_refunded,
                total_credits,
                settlement_adjustment=get_settlement_adjustment(transaction),
            )
            if request.amount > current_balances.credit_balance:
                raise ConflictError(
                    f"Refund exceeds the available customer credit of "
                    f"{current_balances.credit_balance}."
                )

            refund = await self.transaction_refund_repository.create(
                {
                    "transaction_id": transaction_id,
                    **request.model_dump(exclude_none=True),
                }
            )
            await self.activity_service.record(
                farm_id=farm_id,
                user_id=user_id,
                activity_type=ActivityType.TRANSACTION_REFUND_CREATED,
                entity_type=ActivityEntityType.TRANSACTION_REFUND,
                entity_id=refund.id,
                details={
                    "transaction_id": str(transaction_id),
                    "transaction_type": transaction.transaction_type.value,
                    "transaction_reference_number": transaction.reference_number,
                    "amount": str(refund.amount),
                    "payment_method": refund.payment_method.value,
                    "refund_date": refund.refund_date.isoformat(),
                    "reference_number": refund.reference_number,
                    "reason": refund.reason,
                    "notes": refund.notes,
                },
            )

            balances = calculate_transaction_balance(
                transaction_total,
                amount_received,
                amount_refunded + refund.amount,
                total_credits,
                settlement_adjustment=get_settlement_adjustment(transaction),
            )
            await self.unit_of_work.commit()
            logger.info(
                "transaction_refund_created",
                extra={
                    "event": "transaction_refund_created",
                    "farm_id": farm_id,
                    "user_id": user_id,
                    "transaction_id": transaction_id,
                    "refund_id": refund.id,
                    "amount": str(refund.amount),
                },
            )
            return TransactionRefundRecordResponse(
                refund=TransactionRefundResponse.model_validate(refund),
                adjusted_transaction_total=balances.adjusted_transaction_total,
                amount_paid=balances.amount_paid,
                balance_due=balances.balance_due,
                credit_balance=balances.credit_balance,
            )

    async def list_refunds(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> list[TransactionRefundResponse]:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_by_id(
                farm_id,
                transaction_id,
            )
            if transaction is None:
                raise ResourceNotFoundError("Transaction not found for this farm.")
            if transaction.transaction_type != TransactionType.SALE:
                raise ConflictError("Refund history is only available for sale transactions.")
            refunds = await self.transaction_refund_repository.list_by_transaction(
                transaction_id
            )
            return [
                TransactionRefundResponse.model_validate(refund)
                for refund in refunds
            ]
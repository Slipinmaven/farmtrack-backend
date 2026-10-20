from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.transactions import Transaction
from app.repositories.contact_repository import ContactRepository
from app.repositories.purchase_replacement_repository import (
    PurchaseReplacementRepository,
)
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.contact import (
    ContactTransactionHistoryItem,
    ContactTransactionHistoryResponse,
)
from app.schemas.enums import TransactionStatus, TransactionType
from app.services.transaction_balance import (
    TransactionBalance,
    calculate_transaction_balance,
    get_settlement_adjustment,
)


class ContactHistoryService:
    def __init__(
        self,
        contact_repository: ContactRepository,
        transaction_repository: TransactionRepository,
        transaction_refund_repository: TransactionRefundRepository,
        sale_return_repository: SaleReturnRepository,
        supplier_refund_repository: PurchaseSupplierRefundRepository,
        purchase_return_repository: PurchaseReturnRepository,
        purchase_replacement_repository: PurchaseReplacementRepository,
        unit_of_work: UnitOfWork,
    ):
        self.contact_repository = contact_repository
        self.transaction_repository = transaction_repository
        self.transaction_refund_repository = transaction_refund_repository
        self.sale_return_repository = sale_return_repository
        self.supplier_refund_repository = supplier_refund_repository
        self.purchase_return_repository = purchase_return_repository
        self.purchase_replacement_repository = purchase_replacement_repository
        self.unit_of_work = unit_of_work

    async def get_history(
        self,
        farm_id: UUID,
        contact_id: UUID,
        limit: int,
        offset: int,
    ) -> ContactTransactionHistoryResponse:
        async with self.unit_of_work:
            contact = await self.contact_repository.get_by_id(farm_id, contact_id)
            if contact is None:
                raise ResourceNotFoundError("Contact not found for this farm.")

            transactions = await self.transaction_repository.list_by_farm(
                farm_id,
                contact_id=contact_id,
                offset=offset,
                limit=limit,
            )
            items = []
            for transaction in transactions:
                balance = await self._calculate_balance(transaction)
                items.append(
                    ContactTransactionHistoryItem(
                        id=transaction.id,
                        transaction_type=transaction.transaction_type,
                        status=transaction.status,
                        transaction_date=transaction.transaction_date,
                        reference_number=transaction.reference_number,
                        item_count=len(transaction.items),
                        transaction_total=sum(
                            (item.total_amount for item in transaction.items),
                            Decimal("0.00"),
                        ),
                        amount_paid=balance.amount_paid,
                        balance_due=balance.balance_due,
                        credit_balance=balance.credit_balance,
                    )
                )
            return ContactTransactionHistoryResponse(
                items=items,
                total_count=await self.transaction_repository.count_by_farm(
                    farm_id,
                    contact_id,
                ),
                limit=limit,
                offset=offset,
            )

    async def _calculate_balance(
        self,
        transaction: Transaction,
    ) -> TransactionBalance:
        if transaction.status == TransactionStatus.CANCELLED:
            return TransactionBalance(
                adjusted_transaction_total=Decimal("0.00"),
                amount_paid=Decimal("0.00"),
                balance_due=Decimal("0.00"),
                credit_balance=Decimal("0.00"),
            )

        transaction_total = sum(
            (item.total_amount for item in transaction.items),
            Decimal("0.00"),
        )
        amount_paid = sum(
            (payment.amount for payment in transaction.payments),
            Decimal("0.00"),
        )
        if transaction.transaction_type == TransactionType.SALE:
            refunded = (
                await self.transaction_refund_repository.get_total_by_transaction(
                    transaction.id
                )
            )
            credits = (
                await self.sale_return_repository.get_total_credit_by_transaction(
                    transaction.id
                )
            )
        else:
            refunded = await self.supplier_refund_repository.get_total_by_transaction(
                transaction.id
            )
            return_credits = (
                await self.purchase_return_repository.get_total_credit_by_transaction(
                    transaction.id
                )
            )
            replacement_credits = (
                await self.purchase_replacement_repository.get_total_credit_applied_by_transaction(
                    transaction.id
                )
            )
            credits = return_credits
            settlement_adjustment = (
                get_settlement_adjustment(transaction) - replacement_credits
            )
        return calculate_transaction_balance(
            transaction_total,
            amount_paid,
            refunded,
            credits,
            settlement_adjustment=(
                settlement_adjustment
                if transaction.transaction_type == TransactionType.PURCHASE
                else get_settlement_adjustment(transaction)
            ),
        )

from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.unit_of_work import UnitOfWork
from app.core.exceptions import ResourceNotFoundError
from app.models.transactions import Transaction
from app.repositories.contact_repository import ContactRepository
from app.repositories.purchase_replacement_repository import (
    PurchaseReplacementRepository,
)
from app.repositories.purchase_receipt_item_repository import (
    PurchaseReceiptItemRepository,
)
from app.repositories.purchase_receipt_repository import PurchaseReceiptRepository
from app.repositories.purchase_return_repository import PurchaseReturnRepository
from app.repositories.purchase_supplier_refund_repository import (
    PurchaseSupplierRefundRepository,
)
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.chicken_purchase import (
    BlockAllocationResponse,
    ChickenPurchaseDetailResponse,
    ChickenPurchaseResponse,
    PurchaseOutstandingBalanceResponse,
    PurchaseReceiptItemResponse,
    PurchaseReceiptResponse,
)
from app.schemas.enums import TransactionStatus, TransactionType
from app.schemas.payment import PaymentResponse
from app.schemas.transaction import TransactionItemResponse
from app.services.transaction_balance import (
    TransactionBalance,
    calculate_transaction_balance,
    get_settlement_adjustment,
)


def _to_discount_type(
    value: str | None,
) -> Literal["fixed", "percentage"] | None:
    if value == "fixed":
        return "fixed"
    if value == "percentage":
        return "percentage"
    if value is None:
        return None
    raise ValueError(f"Unsupported purchase discount type: {value}")


class ChickenPurchaseDetailsService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        contact_repository: ContactRepository,
        receipt_repository: PurchaseReceiptRepository,
        receipt_item_repository: PurchaseReceiptItemRepository,
        purchase_return_repository: PurchaseReturnRepository,
        purchase_replacement_repository: PurchaseReplacementRepository,
        supplier_refund_repository: PurchaseSupplierRefundRepository,
        unit_of_work: UnitOfWork,
    ):
        self.transaction_repository = transaction_repository
        self.contact_repository = contact_repository
        self.receipt_repository = receipt_repository
        self.receipt_item_repository = receipt_item_repository
        self.purchase_return_repository = purchase_return_repository
        self.purchase_replacement_repository = purchase_replacement_repository
        self.supplier_refund_repository = supplier_refund_repository
        self.unit_of_work = unit_of_work

    async def get_details(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> ChickenPurchaseDetailResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_purchase_detail_by_id(
                farm_id,
                transaction_id,
            )
            if (
                transaction is None
                or transaction.transaction_type != TransactionType.PURCHASE
            ):
                raise ResourceNotFoundError("Purchase not found for this farm.")

            payments = [PaymentResponse.model_validate(p) for p in transaction.payments]
            transaction_total = sum(
                (item.total_amount for item in transaction.items),
                Decimal("0.00"),
            )
            purchase_balance = await self._calculate_balance(transaction)
            received_quantities = (
                await self.receipt_item_repository.get_received_quantities_by_transaction(
                    transaction.id
                )
            )
            items = []
            for item in sorted(
                transaction.items,
                key=lambda record: (record.created_at, record.id),
            ):
                ordered_quantity = item.quantity * item.conversion_factor
                received_quantity = received_quantities.get(item.id, Decimal("0"))
                items.append(
                    TransactionItemResponse(
                        id=item.id,
                        product_id=item.product_id,
                        unit_id=item.unit_id,
                        quantity=item.quantity,
                        conversion_factor=item.conversion_factor,
                        chicken_type=item.chicken_type,
                        ordered_base_quantity=ordered_quantity,
                        unit_price=item.unit_price,
                        subtotal_amount=item.subtotal_amount,
                        discount_amount=item.discount_amount,
                        total_amount=item.total_amount,
                        notes=item.notes,
                        quantity_received=received_quantity,
                        quantity_remaining=ordered_quantity - received_quantity,
                        product_name=item.product.name,
                        unit_name=item.unit.name,
                    )
                )

            purchase = ChickenPurchaseResponse(
                id=transaction.id,
                farm_id=transaction.farm_id,
                contact_id=transaction.contact_id,
                transaction_type=transaction.transaction_type,
                status=transaction.status,
                transaction_date=transaction.transaction_date,
                reference_number=transaction.reference_number,
                notes=transaction.notes,
                discount_type=_to_discount_type(transaction.discount_type),
                discount_value=transaction.discount_value,
                discount_amount=transaction.discount_amount,
                discount_reason=transaction.discount_reason,
                items=items,
                payments=payments,
                transaction_total=transaction_total,
                amount_paid=purchase_balance.amount_paid,
                balance_due=purchase_balance.balance_due,
                credit_balance=purchase_balance.credit_balance,
                created_at=transaction.created_at,
                updated_at=transaction.updated_at,
            )

            receipts = await self.receipt_repository.list_by_transaction(
                transaction.id
            )
            receipt_responses = []
            for receipt in receipts:
                receipt_items = []
                for receipt_item in receipt.items:
                    item = receipt_item.transaction_item
                    batch_link = item.chicken_transaction_item
                    batch = batch_link.batch if batch_link is not None else None
                    ordered_quantity = item.quantity * item.conversion_factor
                    receipt_items.append(
                        PurchaseReceiptItemResponse(
                            id=receipt_item.id,
                            transaction_item_id=item.id,
                            quantity_received=receipt_item.quantity,
                            batch_id=batch.id if batch is not None else None,
                            batch_name=batch.name if batch is not None else None,
                            hatch_date=batch.hatch_date if batch is not None else None,
                            remaining_quantity=(
                                ordered_quantity
                                - received_quantities.get(item.id, Decimal("0"))
                            ),
                            block_allocations=[
                                BlockAllocationResponse(
                                    block_id=allocation.block_id,
                                    quantity=allocation.quantity,
                                    block_name=allocation.block.name,
                                )
                                for allocation in receipt_item.block_allocations
                            ],
                        )
                    )
                receipt_responses.append(
                    PurchaseReceiptResponse(
                        id=receipt.id,
                        transaction_id=receipt.transaction_id,
                        received_date=receipt.received_date,
                        received_time=receipt.received_time,
                        notes=receipt.notes,
                        created_at=receipt.created_at,
                        items=receipt_items,
                    )
                )

            supplier = (
                await self.contact_repository.get_by_id(
                    farm_id,
                    transaction.contact_id,
                )
                if transaction.contact_id is not None
                else None
            )
            outstanding = []
            if transaction.contact_id is not None:
                supplier_purchases = await self.transaction_repository.list_by_farm(
                    farm_id,
                    transaction_type=TransactionType.PURCHASE,
                    contact_id=transaction.contact_id,
                )
                for supplier_purchase in supplier_purchases:
                    if supplier_purchase.status == TransactionStatus.CANCELLED:
                        continue
                    total = sum(
                        (item.total_amount for item in supplier_purchase.items),
                        Decimal("0.00"),
                    )
                    balance = await self._calculate_balance(supplier_purchase)
                    if balance.balance_due > 0 or balance.credit_balance > 0:
                        outstanding.append(
                            PurchaseOutstandingBalanceResponse(
                                id=supplier_purchase.id,
                                reference_number=supplier_purchase.reference_number,
                                transaction_date=supplier_purchase.transaction_date,
                                transaction_total=total,
                                amount_paid=balance.amount_paid,
                                balance_due=balance.balance_due,
                                credit_balance=balance.credit_balance,
                            )
                        )

            return ChickenPurchaseDetailResponse(
                transaction=purchase,
                supplier_name=supplier.name if supplier is not None else None,
                receipts=receipt_responses,
                outstanding_supplier_balances=outstanding,
                supplier_balance_total=sum(
                    (record.balance_due for record in outstanding),
                    Decimal("0.00"),
                ),
                supplier_credit_total=sum(
                    (record.credit_balance for record in outstanding),
                    Decimal("0.00"),
                ),
            )

    async def _calculate_balance(
        self,
        transaction: Transaction,
    ) -> TransactionBalance:
        transaction_total = sum(
            (item.total_amount for item in transaction.items),
            Decimal("0.00"),
        )
        amount_paid = sum(
            (payment.amount for payment in transaction.payments),
            Decimal("0.00"),
        )
        supplier_refunds = (
            await self.supplier_refund_repository.get_total_by_transaction(
                transaction.id
            )
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
        return calculate_transaction_balance(
            transaction_total,
            amount_paid,
            supplier_refunds,
            return_credits,
            settlement_adjustment=(
                get_settlement_adjustment(transaction) - replacement_credits
            ),
        )

from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.exceptions import ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.transactions import Transaction
from app.repositories.contact_repository import ContactRepository
from app.repositories.sale_delivery_repository import SaleDeliveryRepository
from app.repositories.sale_return_repository import SaleReturnRepository
from app.repositories.transaction_refund_repository import TransactionRefundRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.chicken_sale import (
    ChickenSaleAllocationDetailResponse,
    ChickenSaleDeliveryDetailResponse,
    ChickenSaleDeliveryItemDetailResponse,
    ChickenSaleDetailResponse,
    ChickenSaleOutstandingBalanceResponse,
    ChickenSaleResponse,
)
from app.schemas.enums import TransactionStatus, TransactionType
from app.schemas.payment import PaymentResponse
from app.schemas.transaction import TransactionItemResponse
from app.services.transaction_balance import (
    TransactionBalance,
    calculate_transaction_balance,
    get_settlement_adjustment,
)
from app.services.transaction_pricing import calculate_sale_return_credit_total


def _to_discount_type(
    value: str | None,
) -> Literal["fixed", "percentage"] | None:
    if value == "fixed":
        return "fixed"
    if value == "percentage":
        return "percentage"
    if value is None:
        return None
    raise ValueError(f"Unsupported sale discount type: {value}")


class ChickenSaleDetailsService:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        contact_repository: ContactRepository,
        sale_delivery_repository: SaleDeliveryRepository,
        sale_return_repository: SaleReturnRepository,
        transaction_refund_repository: TransactionRefundRepository,
        unit_of_work: UnitOfWork,
    ):
        self.transaction_repository = transaction_repository
        self.contact_repository = contact_repository
        self.sale_delivery_repository = sale_delivery_repository
        self.sale_return_repository = sale_return_repository
        self.transaction_refund_repository = transaction_refund_repository
        self.unit_of_work = unit_of_work

    async def get_details(
        self,
        farm_id: UUID,
        transaction_id: UUID,
    ) -> ChickenSaleDetailResponse:
        async with self.unit_of_work:
            transaction = await self.transaction_repository.get_sale_detail_by_id(
                farm_id,
                transaction_id,
            )
            if (
                transaction is None
                or transaction.transaction_type != TransactionType.SALE
            ):
                raise ResourceNotFoundError("Sale not found for this farm.")

            balance = await self._calculate_balance(transaction)
            transaction_total = sum(
                (item.total_amount for item in transaction.items),
                Decimal("0.00"),
            )
            delivered = (
                await self.sale_delivery_repository.get_delivered_quantities_by_transaction(
                    transaction.id
                )
            )
            items = [
                TransactionItemResponse(
                    id=item.id,
                    product_id=item.product_id,
                    unit_id=item.unit_id,
                    quantity=item.quantity,
                    conversion_factor=item.conversion_factor,
                    chicken_type=item.chicken_type,
                    ordered_base_quantity=item.quantity * item.conversion_factor,
                    unit_price=item.unit_price,
                    subtotal_amount=item.subtotal_amount,
                    discount_amount=item.discount_amount,
                    total_amount=item.total_amount,
                    notes=item.notes,
                    quantity_received=(
                        item.quantity * item.conversion_factor
                        if item.product.product_type.value == "eggs"
                        and not transaction.fulfillment_required
                        else delivered.get(item.id, Decimal("0"))
                    ),
                    quantity_remaining=(
                        Decimal("0")
                        if item.product.product_type.value == "eggs"
                        and not transaction.fulfillment_required
                        else item.quantity * item.conversion_factor
                        - delivered.get(item.id, Decimal("0"))
                    ),
                    product_name=item.product.name,
                    product_type=item.product.product_type,
                    unit_name=item.unit.name,
                )
                for item in sorted(
                    transaction.items,
                    key=lambda record: (record.created_at, record.id),
                )
            ]
            sale = ChickenSaleResponse(
                id=transaction.id,
                farm_id=transaction.farm_id,
                contact_id=transaction.contact_id,
                transaction_type=transaction.transaction_type,
                status=transaction.status,
                transaction_date=transaction.transaction_date,
                transaction_time=transaction.transaction_time,
                reference_number=transaction.reference_number,
                notes=transaction.notes,
                discount_type=_to_discount_type(transaction.discount_type),
                discount_value=transaction.discount_value,
                discount_amount=transaction.discount_amount,
                discount_reason=transaction.discount_reason,
                items=items,
                payments=[
                    PaymentResponse.model_validate(payment)
                    for payment in transaction.payments
                ],
                transaction_total=transaction_total,
                amount_paid=balance.amount_paid,
                balance_due=balance.balance_due,
                credit_balance=balance.credit_balance,
                created_at=transaction.created_at,
                updated_at=transaction.updated_at,
            )

            customer = (
                await self.contact_repository.get_by_id(
                    farm_id,
                    transaction.contact_id,
                )
                if transaction.contact_id is not None
                else None
            )
            deliveries = await self.sale_delivery_repository.list_by_transaction(
                transaction.id
            )
            delivery_details = [
                ChickenSaleDeliveryDetailResponse(
                    id=delivery.id,
                    delivered_date=delivery.delivered_date,
                    delivered_time=delivery.delivered_time,
                    notes=delivery.notes,
                    items=[
                        ChickenSaleDeliveryItemDetailResponse(
                            id=delivery_item.id,
                            transaction_item_id=delivery_item.transaction_item_id,
                            quantity=delivery_item.quantity,
                            batch_allocations=[
                                ChickenSaleAllocationDetailResponse(
                                    batch_id=allocation.batch_id,
                                    batch_name=allocation.batch.name,
                                    block_id=allocation.block_id,
                                    block_name=allocation.block.name,
                                    quantity=allocation.quantity,
                                )
                                for allocation in delivery_item.batch_allocations
                            ],
                        )
                        for delivery_item in delivery.items
                    ],
                )
                for delivery in deliveries
            ]

            outstanding: list[ChickenSaleOutstandingBalanceResponse] = []
            if transaction.contact_id is not None:
                customer_sales = await self.transaction_repository.list_by_farm(
                    farm_id,
                    transaction_type=TransactionType.SALE,
                    contact_id=transaction.contact_id,
                )
                for customer_sale in customer_sales:
                    if customer_sale.status == TransactionStatus.CANCELLED:
                        continue
                    customer_balance = await self._calculate_balance(customer_sale)
                    if (
                        customer_balance.balance_due > 0
                        or customer_balance.credit_balance > 0
                    ):
                        customer_total = sum(
                            (item.total_amount for item in customer_sale.items),
                            Decimal("0.00"),
                        )
                        outstanding.append(
                            ChickenSaleOutstandingBalanceResponse(
                                id=customer_sale.id,
                                reference_number=customer_sale.reference_number,
                                transaction_date=customer_sale.transaction_date,
                                transaction_total=customer_total,
                                amount_paid=customer_balance.amount_paid,
                                balance_due=customer_balance.balance_due,
                                credit_balance=customer_balance.credit_balance,
                            )
                        )

            return ChickenSaleDetailResponse(
                transaction=sale,
                customer_name=customer.name if customer is not None else None,
                deliveries=delivery_details,
                outstanding_customer_balances=outstanding,
                customer_balance_total=sum(
                    (record.balance_due for record in outstanding),
                    Decimal("0.00"),
                ),
                customer_credit_total=sum(
                    (record.credit_balance for record in outstanding),
                    Decimal("0.00"),
                ),
            )

    async def _calculate_balance(self, transaction: Transaction) -> TransactionBalance:
        transaction_total = sum(
            (item.total_amount for item in transaction.items),
            Decimal("0.00"),
        )
        amount_received = sum(
            (payment.amount for payment in transaction.payments),
            Decimal("0.00"),
        )
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
        sale_credits = calculate_sale_return_credit_total(
            transaction.items,
            returned_quantities,
        )
        return calculate_transaction_balance(
            transaction_total,
            amount_received,
            amount_refunded,
            sale_credits,
            settlement_adjustment=get_settlement_adjustment(transaction),
        )

from uuid import UUID
from decimal import Decimal

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.repositories.product_repository import ProductRepository
from app.repositories.farm_repository import FarmRepository
from app.schemas.chicken_purchase import ChickenPurchaseRequest
from app.schemas.enums import ProductType, TransactionStatus, TransactionType
from app.schemas.transaction import TransactionCreate, TransactionItemCreate
from app.services.transaction_service import TransactionService
from app.services.transaction_pricing import (
    calculate_discount_allocation,
    validate_payment_confirmation,
)


class ChickenPurchaseService:
    def __init__(
        self,
        product_repository: ProductRepository,
        transaction_service: TransactionService,
        farm_repository: FarmRepository | None = None,
    ):
        self.product_repository = product_repository
        self.transaction_service = transaction_service
        self.farm_repository = farm_repository

    async def create_chicken_purchase(
        self,
        farm_id: UUID,
        purchase_request: ChickenPurchaseRequest,
        user_id: UUID | None = None,
    ):
        if self.farm_repository is not None:
            farm = await self.farm_repository.get_by_id_for_update(farm_id)
            if farm is None:
                raise ResourceNotFoundError("Farm not found.")
        transaction_items = []
        for purchase_item in purchase_request.items:
            product = await self.product_repository.get_by_id(
                farm_id,
                purchase_item.product_id,
            )
            if product is None:
                raise ResourceNotFoundError("Product not found for this farm.")
            if not product.is_active:
                raise ConflictError("Inactive products cannot be purchased.")
            if product.product_type != ProductType.CHICKENS:
                raise ConflictError("Chicken purchases require chicken products.")
            transaction_items.append(
                TransactionItemCreate(
                    product_id=product.id,
                    chicken_type=purchase_item.chicken_type,
                    unit_id=purchase_item.unit_id,
                    quantity=Decimal(str(purchase_item.quantity)),
                    unit_price=purchase_item.unit_price,
                    notes=purchase_item.notes,
                )
            )

        line_subtotals = [
            Decimal(purchase_item.quantity) * purchase_item.unit_price
            for purchase_item in purchase_request.items
        ]
        try:
            discount_amount, _ = calculate_discount_allocation(
                line_subtotals,
                purchase_request.discount_type,
                purchase_request.discount_value,
            )
            final_total = sum(line_subtotals, Decimal("0.00")) - discount_amount
            validate_payment_confirmation(
                final_total,
                [payment.amount for payment in purchase_request.payments],
                purchase_request.overpayment_confirmed,
            )
        except ValueError as error:
            raise ConflictError(str(error)) from error

        transaction_data = TransactionCreate(
            transaction_type=TransactionType.PURCHASE,
            transaction_date=purchase_request.transaction_date,
            status=TransactionStatus.COMPLETED,
            contact_id=purchase_request.supplier_id,
            notes=purchase_request.notes,
            items=transaction_items,
            payments=purchase_request.payments,
            discount_type=purchase_request.discount_type,
            discount_value=purchase_request.discount_value,
            discount_reason=purchase_request.discount_reason,
        )
        return await self.transaction_service.create_transaction(
            farm_id,
            transaction_data,
            user_id,
        )
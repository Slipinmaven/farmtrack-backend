from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.repositories.product_repository import ProductRepository
from app.schemas.enums import ProductType, TransactionStatus, TransactionType
from app.schemas.inventory import InventoryPurchaseRequest
from app.schemas.transaction import (
    TransactionCreate,
    TransactionItemCreate,
    TransactionResponse,
)
from app.services.transaction_service import TransactionService


class InventoryPurchaseService:
    def __init__(
        self,
        product_repository: ProductRepository,
        transaction_service: TransactionService,
    ) -> None:
        self.product_repository = product_repository
        self.transaction_service = transaction_service

    async def create_purchase(
        self,
        farm_id: UUID,
        request: InventoryPurchaseRequest,
        user_id: UUID | None = None,
    ) -> TransactionResponse:
        items = []
        purchase_total = Decimal("0.00")
        for item in request.items:
            product = await self.product_repository.get_by_id(
                farm_id,
                item.product_id,
            )
            if product is None:
                raise ResourceNotFoundError("Product not found for this farm.")
            if not product.is_active:
                raise ConflictError("Inactive products cannot be purchased.")
            if product.product_type in {ProductType.CHICKENS, ProductType.EGGS}:
                raise ConflictError(
                    "Use the dedicated chicken or egg workflow to record those purchases."
                )
            items.append(
                TransactionItemCreate(
                    product_id=product.id,
                    unit_id=item.unit_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
            )
            purchase_total += (item.quantity * item.unit_price).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        total_paid = sum(
            (payment.amount for payment in request.payments),
            Decimal("0.00"),
        )
        if total_paid > purchase_total:
            raise ConflictError("Payments cannot exceed the total purchase amount.")

        transaction = TransactionCreate(
            transaction_type=TransactionType.PURCHASE,
            transaction_date=request.transaction_date,
            status=TransactionStatus.COMPLETED,
            contact_id=request.supplier_id,
            notes=request.notes,
            items=items,
            payments=request.payments,
        )
        return await self.transaction_service.create_transaction(
            farm_id,
            transaction,
            user_id,
        )

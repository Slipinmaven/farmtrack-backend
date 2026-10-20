from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.purchase_receipt_items import PurchaseReceiptItem
from app.models.purchase_receipts import PurchaseReceipt


class PurchaseReceiptItemRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_receipt(self, receipt_id: UUID) -> list[PurchaseReceiptItem]:
        result = await self.session.execute(
            select(PurchaseReceiptItem)
            .options(selectinload(PurchaseReceiptItem.transaction_item))
            .where(PurchaseReceiptItem.purchase_receipt_id == receipt_id)
            .order_by(PurchaseReceiptItem.created_at, PurchaseReceiptItem.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, receipt_item_id: UUID) -> PurchaseReceiptItem | None:
        result = await self.session.execute(
            select(PurchaseReceiptItem)
            .options(selectinload(PurchaseReceiptItem.transaction_item))
            .where(PurchaseReceiptItem.id == receipt_item_id)
        )
        return result.scalar_one_or_none()

    async def get_received_quantities_by_transaction(
        self,
        transaction_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(
                PurchaseReceiptItem.transaction_item_id,
                func.sum(PurchaseReceiptItem.quantity),
            )
            .join(
                PurchaseReceipt,
                PurchaseReceipt.id == PurchaseReceiptItem.purchase_receipt_id,
            )
            .where(PurchaseReceipt.transaction_id == transaction_id)
            .group_by(PurchaseReceiptItem.transaction_item_id)
        )
        return {
            transaction_item_id: quantity
            for transaction_item_id, quantity in result.all()
        }

    async def create(self, receipt_item_data: dict) -> PurchaseReceiptItem:
        receipt_item = PurchaseReceiptItem(**receipt_item_data)
        self.session.add(receipt_item)
        await self.session.flush()
        return receipt_item

    async def update(self, receipt_item: PurchaseReceiptItem) -> PurchaseReceiptItem:
        await self.session.flush()
        await self.session.refresh(receipt_item)
        return receipt_item

    async def delete(self, receipt_item: PurchaseReceiptItem) -> None:
        await self.session.delete(receipt_item)
        await self.session.flush()

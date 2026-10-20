from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chicken_transaction_items import ChickenTransactionItem
from app.models.purchase_receipt_items import PurchaseReceiptItem
from app.models.purchase_receipts import PurchaseReceipt
from app.models.purchase_receipt_item_block_allocations import (
    PurchaseReceiptItemBlockAllocation,
)
from app.models.transaction_items import TransactionItem
from app.models.transactions import Transaction


class PurchaseReceiptRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _receipt_query(self):
        item_loader = selectinload(PurchaseReceipt.items)
        transaction_item_loader = item_loader.selectinload(
            PurchaseReceiptItem.transaction_item
        )
        return select(PurchaseReceipt).options(
            transaction_item_loader.selectinload(
                TransactionItem.chicken_transaction_item
            ).selectinload(ChickenTransactionItem.batch),
            item_loader.selectinload(
                PurchaseReceiptItem.block_allocations
            ).selectinload(PurchaseReceiptItemBlockAllocation.block),
        )

    async def list_by_transaction(self, transaction_id: UUID) -> list[PurchaseReceipt]:
        result = await self.session.execute(
            self._receipt_query()
            .where(PurchaseReceipt.transaction_id == transaction_id)
            .order_by(
                PurchaseReceipt.received_date,
                PurchaseReceipt.received_time,
                PurchaseReceipt.id,
            )
        )
        return list(result.scalars().all())

    async def list_by_farm(self, farm_id: UUID) -> list[PurchaseReceipt]:
        result = await self.session.execute(
            self._receipt_query()
            .join(Transaction, Transaction.id == PurchaseReceipt.transaction_id)
            .where(Transaction.farm_id == farm_id)
            .order_by(
                PurchaseReceipt.received_date.desc(),
                PurchaseReceipt.received_time.desc(),
                PurchaseReceipt.id,
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, receipt_id: UUID) -> PurchaseReceipt | None:
        result = await self.session.execute(
            self._receipt_query()
            .where(PurchaseReceipt.id == receipt_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_farm(
        self,
        farm_id: UUID,
        receipt_id: UUID,
    ) -> PurchaseReceipt | None:
        result = await self.session.execute(
            self._receipt_query()
            .join(Transaction, Transaction.id == PurchaseReceipt.transaction_id)
            .where(
                Transaction.farm_id == farm_id,
                PurchaseReceipt.id == receipt_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, receipt_data: dict) -> PurchaseReceipt:
        receipt = PurchaseReceipt(**receipt_data)
        self.session.add(receipt)
        await self.session.flush()
        return receipt

    async def update(self, receipt: PurchaseReceipt) -> PurchaseReceipt:
        await self.session.flush()
        await self.session.refresh(receipt)
        return receipt

    async def delete(self, receipt: PurchaseReceipt) -> None:
        await self.session.delete(receipt)
        await self.session.flush()

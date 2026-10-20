from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.sale_deliveries import SaleDelivery
from app.models.sale_delivery_item_allocations import SaleDeliveryItemAllocation
from app.models.sale_delivery_items import SaleDeliveryItem
from app.models.sale_delivery_item_allocations import SaleDeliveryItemAllocation


class SaleDeliveryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _delivery_query(self):
        return select(SaleDelivery).options(
            selectinload(SaleDelivery.items)
            .selectinload(SaleDeliveryItem.batch_allocations)
            .selectinload(SaleDeliveryItemAllocation.batch),
            selectinload(SaleDelivery.items)
            .selectinload(SaleDeliveryItem.batch_allocations)
            .selectinload(SaleDeliveryItemAllocation.block),
        )

    async def list_by_transaction(self, transaction_id: UUID) -> list[SaleDelivery]:
        result = await self.session.execute(
            self._delivery_query()
            .where(SaleDelivery.transaction_id == transaction_id)
            .order_by(
                SaleDelivery.delivered_date,
                SaleDelivery.delivered_time,
                SaleDelivery.created_at,
                SaleDelivery.id,
            )
        )
        return list(result.scalars().all())

    async def get_delivered_quantities_by_transaction(
        self,
        transaction_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = await self.session.execute(
            select(
                SaleDeliveryItem.transaction_item_id,
                func.sum(SaleDeliveryItem.quantity),
            )
            .join(
                SaleDelivery,
                SaleDelivery.id == SaleDeliveryItem.sale_delivery_id,
            )
            .where(SaleDelivery.transaction_id == transaction_id)
            .group_by(SaleDeliveryItem.transaction_item_id)
        )
        return {
            transaction_item_id: quantity
            for transaction_item_id, quantity in result.all()
        }

    async def get_delivered_quantities_by_batch(
        self,
        transaction_id: UUID,
    ) -> dict[tuple[UUID, UUID], int]:
        result = await self.session.execute(
            select(
                SaleDeliveryItem.transaction_item_id,
                SaleDeliveryItemAllocation.batch_id,
                func.sum(SaleDeliveryItemAllocation.quantity),
            )
            .join(
                SaleDelivery,
                SaleDelivery.id == SaleDeliveryItem.sale_delivery_id,
            )
            .join(
                SaleDeliveryItemAllocation,
                SaleDeliveryItemAllocation.sale_delivery_item_id == SaleDeliveryItem.id,
            )
            .where(SaleDelivery.transaction_id == transaction_id)
            .group_by(
                SaleDeliveryItem.transaction_item_id,
                SaleDeliveryItemAllocation.batch_id,
            )
        )
        return {
            (transaction_item_id, batch_id): quantity
            for transaction_item_id, batch_id, quantity in result.all()
        }

    async def create_delivery(self, data: dict) -> SaleDelivery:
        delivery = SaleDelivery(**data)
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def create_item(self, data: dict) -> SaleDeliveryItem:
        item = SaleDeliveryItem(**data)
        self.session.add(item)
        await self.session.flush()
        return item

    async def create_allocation(self, data: dict) -> None:
        from app.models.sale_delivery_item_allocations import SaleDeliveryItemAllocation

        self.session.add(SaleDeliveryItemAllocation(**data))
        await self.session.flush()
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction_items import TransactionItem
from app.models.transactions import Transaction
from app.models.sale_return_items import SaleReturnItem
from app.models.sale_returns import SaleReturn
from app.schemas.enums import TransactionStatus, TransactionType


class TransactionItemRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_transaction(self, transaction_id: UUID) -> list[TransactionItem]:
        result = await self.session.execute(
            select(TransactionItem)
            .options(
                selectinload(TransactionItem.product),
                selectinload(TransactionItem.unit),
                selectinload(TransactionItem.chicken_transaction_item),
            )
            .where(TransactionItem.transaction_id == transaction_id)
            .order_by(TransactionItem.created_at, TransactionItem.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, item_id: UUID) -> TransactionItem | None:
        result = await self.session.execute(
            select(TransactionItem)
            .options(
                selectinload(TransactionItem.product),
                selectinload(TransactionItem.unit),
                selectinload(TransactionItem.chicken_transaction_item),
            )
            .where(TransactionItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def create(self, item_data: dict) -> TransactionItem:
        item = TransactionItem(**item_data)
        self.session.add(item)
        await self.session.flush()
        return item

    async def update(self, item: TransactionItem) -> TransactionItem:
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def delete(self, item: TransactionItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

    async def get_sold_base_quantities_by_farm(
        self,
        farm_id: UUID,
    ) -> dict[UUID, Decimal]:
        returned_quantities = (
            select(
                SaleReturnItem.transaction_item_id,
                func.sum(SaleReturnItem.quantity).label("quantity"),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .group_by(SaleReturnItem.transaction_item_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                TransactionItem.product_id,
                func.sum(
                    TransactionItem.quantity * TransactionItem.conversion_factor
                    - func.coalesce(returned_quantities.c.quantity, 0)
                ),
            )
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .outerjoin(
                returned_quantities,
                returned_quantities.c.transaction_item_id == TransactionItem.id,
            )
            .where(
                Transaction.farm_id == farm_id,
                Transaction.transaction_type == TransactionType.SALE,
                Transaction.status == TransactionStatus.COMPLETED,
            )
            .group_by(TransactionItem.product_id)
        )
        return {
            product_id: Decimal(quantity)
            for product_id, quantity in result.all()
        }

    async def get_sold_base_quantity(
        self,
        farm_id: UUID,
        product_id: UUID,
    ) -> Decimal:
        returned_quantities = (
            select(
                SaleReturnItem.transaction_item_id,
                func.sum(SaleReturnItem.quantity).label("quantity"),
            )
            .join(SaleReturn, SaleReturn.id == SaleReturnItem.sale_return_id)
            .group_by(SaleReturnItem.transaction_item_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(
                        TransactionItem.quantity * TransactionItem.conversion_factor
                        - func.coalesce(returned_quantities.c.quantity, 0)
                    ),
                    0,
                )
            )
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .outerjoin(
                returned_quantities,
                returned_quantities.c.transaction_item_id == TransactionItem.id,
            )
            .where(
                Transaction.farm_id == farm_id,
                Transaction.transaction_type == TransactionType.SALE,
                Transaction.status == TransactionStatus.COMPLETED,
                TransactionItem.product_id == product_id,
            )
        )
        return Decimal(result.scalar_one())

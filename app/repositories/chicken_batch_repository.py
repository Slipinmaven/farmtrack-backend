from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chicken_batches import ChickenBatch
from app.models.batch_blocks import BatchBlock
from app.models.blocks import Block
from app.models.chicken_transaction_items import ChickenTransactionItem
from app.models.transaction_items import TransactionItem
from app.models.transactions import Transaction
from app.schemas.enums import ChickenBatchStatus, TransactionStatus, TransactionType


class ChickenBatchRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_farm(
        self,
        farm_id: UUID,
        search: str | None = None,
        status: ChickenBatchStatus | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ChickenBatch]:
        query = select(ChickenBatch).where(ChickenBatch.farm_id == farm_id)
        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(ChickenBatch.name.ilike(term), ChickenBatch.breed.ilike(term))
            )
        if status is not None:
            query = query.where(ChickenBatch.status == status)
        query = query.options(selectinload(ChickenBatch.batch_blocks))
        query = query.order_by(ChickenBatch.created_at.desc(), ChickenBatch.name)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, farm_id: UUID, batch_id: UUID) -> ChickenBatch | None:
        result = await self.session.execute(
            select(ChickenBatch)
            .options(selectinload(ChickenBatch.batch_blocks))
            .where(ChickenBatch.farm_id == farm_id, ChickenBatch.id == batch_id)
        )
        return result.scalar_one_or_none()

    async def list_for_settlement(
        self,
        farm_id: UUID,
        *,
        search: str | None,
        require_active_stock: bool,
        block_id: UUID | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[tuple[ChickenBatch, int]]:
        query = (
            select(
                ChickenBatch,
                func.coalesce(func.sum(BatchBlock.quantity), 0),
            )
            .outerjoin(
                BatchBlock,
                and_(
                    BatchBlock.batch_id == ChickenBatch.id,
                    BatchBlock.quantity > 0,
                ),
            )
            .where(
                ChickenBatch.farm_id == farm_id,
                ChickenBatch.status == ChickenBatchStatus.ACTIVE,
            )
        )
        if require_active_stock:
            query = query.join(Block, Block.id == BatchBlock.block_id).where(
                Block.is_active.is_(True),
                Block.farm_id == farm_id,
            )
        if block_id is not None:
            if not require_active_stock:
                query = query.join(Block, Block.id == BatchBlock.block_id).where(
                    Block.is_active.is_(True),
                    Block.farm_id == farm_id,
                )
            query = query.where(Block.id == block_id)
        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(ChickenBatch.name.ilike(term), ChickenBatch.breed.ilike(term))
            )
        query = (
            query.group_by(ChickenBatch.id)
            .order_by(ChickenBatch.created_at.desc(), ChickenBatch.name)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return [
            (batch, int(total_quantity))
            for batch, total_quantity in result.all()
        ]

    async def get_estimated_purchase_unit_costs(
        self,
        farm_id: UUID,
        batch_ids: set[UUID],
    ) -> dict[UUID, Decimal]:
        if not batch_ids:
            return {}

        result = await self.session.execute(
            select(
                ChickenTransactionItem.batch_id,
                TransactionItem.total_amount,
                TransactionItem.quantity,
                TransactionItem.conversion_factor,
            )
            .join(
                TransactionItem,
                TransactionItem.id == ChickenTransactionItem.transaction_item_id,
            )
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .where(
                ChickenTransactionItem.batch_id.in_(batch_ids),
                Transaction.farm_id == farm_id,
                Transaction.transaction_type == TransactionType.PURCHASE,
                Transaction.status == TransactionStatus.COMPLETED,
                (TransactionItem.quantity * TransactionItem.conversion_factor) > 0,
            )
        )
        totals: dict[UUID, tuple[Decimal, Decimal]] = {}
        for batch_id, total_amount, quantity, conversion_factor in result.all():
            base_quantity = Decimal(quantity) * Decimal(conversion_factor)
            total_cost, total_units = totals.get(
                batch_id,
                (Decimal("0"), Decimal("0")),
            )
            totals[batch_id] = (
                total_cost + Decimal(total_amount),
                total_units + base_quantity,
            )

        return {
            batch_id: (total_cost / total_units).quantize(Decimal("0.0001"))
            for batch_id, (total_cost, total_units) in totals.items()
            if total_units > 0
        }

    async def create(self, farm_id: UUID, batch_data: dict) -> ChickenBatch:
        batch = ChickenBatch(farm_id=farm_id, **batch_data)
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def update(self, batch: ChickenBatch) -> ChickenBatch:
        await self.session.flush()
        await self.session.refresh(batch)
        return batch

    async def delete(self, batch: ChickenBatch) -> None:
        await self.session.delete(batch)
        await self.session.flush()

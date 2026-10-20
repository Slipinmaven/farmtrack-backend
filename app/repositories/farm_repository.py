from uuid import UUID
from sqlalchemy import delete, select, or_
from sqlalchemy.orm import selectinload

from app.models.contact import Contact
from app.models.contact_roles import ContactRole
from app.models.batch_blocks import BatchBlock
from app.models.blocks import Block
from app.models.chicken_batches import ChickenBatch
from app.models.farm import Farm
from app.models.farm_settings import FarmSettings
from app.models.products import Product
from app.models.product_units import ProductUnit
from app.models.chicken_transaction_items import ChickenTransactionItem
from app.models.purchase_receipt_items import PurchaseReceiptItem
from app.models.purchase_receipts import PurchaseReceipt
from app.models.transaction_items import TransactionItem
from app.models.transactions import Transaction

class FarmRepository:
    def __init__(self, session):
        self.session = session

    async def get_by_id(self, farm_id: UUID) -> Farm | None:
        result = await self.session.execute(select(Farm).where(Farm.id == farm_id))
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, farm_id: UUID) -> Farm | None:
        result = await self.session.execute(
            select(Farm).where(Farm.id == farm_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_user_farms(self, owner_id: UUID, search: str | None = None, is_active: bool | None = None) -> list[Farm]:
        query = (
            select(Farm)
            .options(selectinload(Farm.farm_settings))
            .where(Farm.owner_id == owner_id)
        )

        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Farm.name.ilike(term),
                    Farm.description.ilike(term),
                    Farm.location.ilike(term),
                    Farm.phone_number.ilike(term),
                    Farm.email.ilike(term),
                )
            )

        if is_active is not None:
            query = query.where(Farm.is_active == is_active)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def create(self, farm_data: dict) -> Farm:
        farm = Farm(**farm_data)
        self.session.add(farm)
        await self.session.flush() 
        return farm

    async def update(self, farm: Farm) -> Farm:
        await self.session.flush()
        await self.session.refresh(farm)
        return farm

    async def delete(self, farm: Farm) -> None:
        contact_ids = select(Contact.id).where(Contact.farm_id == farm.id)
        product_ids = select(Product.id).where(Product.farm_id == farm.id)
        batch_ids = select(ChickenBatch.id).where(ChickenBatch.farm_id == farm.id)
        block_ids = select(Block.id).where(Block.farm_id == farm.id)
        transaction_ids = select(Transaction.id).where(Transaction.farm_id == farm.id)
        transaction_item_ids = select(TransactionItem.id).where(
            TransactionItem.transaction_id.in_(transaction_ids)
        )
        receipt_ids = select(PurchaseReceipt.id).where(
            PurchaseReceipt.transaction_id.in_(transaction_ids)
        )
        await self.session.execute(
            delete(PurchaseReceiptItem).where(
                or_(
                    PurchaseReceiptItem.purchase_receipt_id.in_(receipt_ids),
                    PurchaseReceiptItem.transaction_item_id.in_(transaction_item_ids),
                )
            )
        )
        await self.session.execute(
            delete(ChickenTransactionItem).where(
                ChickenTransactionItem.transaction_item_id.in_(transaction_item_ids)
            )
        )
        await self.session.execute(
            delete(PurchaseReceipt).where(PurchaseReceipt.transaction_id.in_(transaction_ids))
        )
        await self.session.execute(
            delete(TransactionItem).where(TransactionItem.transaction_id.in_(transaction_ids))
        )
        await self.session.execute(delete(Transaction).where(Transaction.farm_id == farm.id))
        await self.session.execute(
            delete(ContactRole).where(ContactRole.contact_id.in_(contact_ids))
        )
        await self.session.execute(delete(Contact).where(Contact.farm_id == farm.id))
        await self.session.execute(
            delete(BatchBlock).where(
                or_(
                    BatchBlock.batch_id.in_(batch_ids),
                    BatchBlock.block_id.in_(block_ids),
                )
            )
        )
        await self.session.execute(
            delete(ProductUnit).where(ProductUnit.product_id.in_(product_ids))
        )
        await self.session.execute(delete(Product).where(Product.farm_id == farm.id))
        await self.session.execute(
            delete(ChickenBatch).where(ChickenBatch.farm_id == farm.id)
        )
        await self.session.execute(delete(Block).where(Block.farm_id == farm.id))
        await self.session.execute(
            delete(FarmSettings).where(FarmSettings.farm_id == farm.id)
        )
        await self.session.execute(delete(Farm).where(Farm.id == farm.id))
        await self.session.flush()
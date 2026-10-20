from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_role_products import ContactRoleProduct
from app.models.products import Product


class ContactRoleProductRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_product(self, product_id: UUID) -> Product | None:
        result = await self.session.execute(
            select(Product).where(Product.id == product_id)
        )
        return result.scalar_one_or_none()

    async def get_association(
        self,
        contact_role_id: UUID,
        product_id: UUID,
    ) -> ContactRoleProduct | None:
        result = await self.session.execute(
            select(ContactRoleProduct).where(
                ContactRoleProduct.contact_role_id == contact_role_id,
                ContactRoleProduct.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_role(
        self,
        contact_role_id: UUID,
    ) -> list[tuple[ContactRoleProduct, Product]]:
        result = await self.session.execute(
            select(ContactRoleProduct, Product)
            .join(Product, Product.id == ContactRoleProduct.product_id)
            .where(ContactRoleProduct.contact_role_id == contact_role_id)
            .order_by(Product.name, Product.id)
        )
        return list(result.all())

    async def create(
        self,
        contact_role_id: UUID,
        product_id: UUID,
    ) -> ContactRoleProduct:
        association = ContactRoleProduct(
            contact_role_id=contact_role_id,
            product_id=product_id,
        )
        self.session.add(association)
        await self.session.flush()
        return association

    async def delete(self, association: ContactRoleProduct) -> None:
        await self.session.delete(association)
        await self.session.flush()
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_roles import ContactRole


class ContactRoleRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_contact(self, contact_id: UUID) -> list[ContactRole]:
        result = await self.session.execute(
            select(ContactRole)
            .where(ContactRole.contact_id == contact_id)
            .order_by(ContactRole.role, ContactRole.id)
        )
        return list(result.scalars().all())

    async def get_by_id(
        self,
        contact_id: UUID,
        role_id: UUID,
    ) -> ContactRole | None:
        result = await self.session.execute(
            select(ContactRole).where(
                ContactRole.contact_id == contact_id,
                ContactRole.id == role_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, contact_id: UUID, role: str) -> ContactRole:
        contact_role = ContactRole(contact_id=contact_id, role=role)
        self.session.add(contact_role)
        await self.session.flush()
        return contact_role

    async def update(self, contact_role: ContactRole) -> ContactRole:
        await self.session.flush()
        await self.session.refresh(contact_role)
        return contact_role

    async def delete(self, contact_role: ContactRole) -> None:
        await self.session.delete(contact_role)
        await self.session.flush()
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contact import Contact
from app.models.contact_roles import ContactRole
from app.schemas.enums import ContactRoleEnum


class ContactRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_farm(
        self,
        farm_id: UUID,
        search: str | None = None,
        role: ContactRoleEnum | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Contact]:
        query = (
            select(Contact)
            .options(selectinload(Contact.contact_roles))
            .where(Contact.farm_id == farm_id)
        )
        if search is not None:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Contact.name.ilike(term),
                    Contact.phone.ilike(term),
                    Contact.email.ilike(term),
                    Contact.address.ilike(term),
                )
            )
        if role is not None:
            query = query.where(
                Contact.contact_roles.any(ContactRole.role == role)
            )
        query = query.order_by(Contact.name, Contact.id)
        if limit is not None:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, farm_id: UUID, contact_id: UUID) -> Contact | None:
        result = await self.session.execute(
            select(Contact)
            .options(selectinload(Contact.contact_roles))
            .where(Contact.farm_id == farm_id, Contact.id == contact_id)
        )
        return result.scalar_one_or_none()

    async def create(self, farm_id: UUID, contact_data: dict) -> Contact:
        contact = Contact(farm_id=farm_id, **contact_data)
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def update(self, contact: Contact) -> Contact:
        await self.session.flush()
        await self.session.refresh(contact)
        return contact

    async def delete(self, contact: Contact) -> None:
        await self.session.execute(
            delete(ContactRole).where(ContactRole.contact_id == contact.id)
        )
        await self.session.execute(
            delete(Contact).where(
                Contact.id == contact.id,
                Contact.farm_id == contact.farm_id,
            )
        )
        await self.session.flush()
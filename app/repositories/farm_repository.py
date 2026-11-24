from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models.farm import Farm
from app.models.farm_membership import FarmMembership

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

    async def get_by_owner_and_id_for_update(
        self,
        farm_id: UUID,
        owner_id: UUID,
    ) -> Farm | None:
        result = await self.session.execute(
            select(Farm)
            .options(selectinload(Farm.farm_settings))
            .where(Farm.id == farm_id, Farm.owner_id == owner_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_owned_for_update(self, owner_id: UUID) -> list[Farm]:
        result = await self.session.execute(
            select(Farm)
            .where(Farm.owner_id == owner_id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def list_pending_deletions_for_owner(
        self,
        owner_id: UUID,
    ) -> list[Farm]:
        result = await self.session.execute(
            select(Farm)
            .options(selectinload(Farm.farm_settings))
            .where(
                Farm.owner_id == owner_id,
                Farm.deletion_requested_at.is_not(None),
            )
            .order_by(Farm.deletion_requested_at, Farm.id)
        )
        return list(result.scalars().all())

    async def get_membership(
        self,
        farm_id: UUID,
        user_id: UUID,
    ) -> FarmMembership | None:
        result = await self.session.execute(
            select(FarmMembership).where(
                FarmMembership.farm_id == farm_id,
                FarmMembership.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_memberships_for_user_for_update(
        self,
        user_id: UUID,
    ) -> list[FarmMembership]:
        result = await self.session.execute(
            select(FarmMembership)
            .where(FarmMembership.user_id == user_id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def get_user_farms(self, user_id: UUID, search: str | None = None, is_active: bool | None = None) -> list[Farm]:
        query = (
            select(Farm)
            .options(selectinload(Farm.farm_settings))
            .join(FarmMembership, FarmMembership.farm_id == Farm.id)
            .where(
                FarmMembership.user_id == user_id,
                FarmMembership.status == "active",
                Farm.deletion_requested_at.is_(None),
            )
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
        self.session.add(
            FarmMembership(
                farm_id=farm.id,
                user_id=farm.owner_id,
                role="owner",
                status="active",
                accepted_at=datetime.now(timezone.utc),
            )
        )
        return farm

    async def update(self, farm: Farm) -> Farm:
        await self.session.flush()
        await self.session.refresh(farm)
        return farm

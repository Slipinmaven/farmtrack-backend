from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.farm_membership import FarmMembership


class FarmMembershipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id_for_update(self, membership_id: UUID) -> FarmMembership | None:
        result = await self.session.execute(
            select(FarmMembership)
            .options(
                selectinload(FarmMembership.user),
                selectinload(FarmMembership.farm),
            )
            .where(FarmMembership.id == membership_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_farm_and_user(
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

    async def list_by_farm(self, farm_id: UUID) -> list[FarmMembership]:
        result = await self.session.execute(
            select(FarmMembership)
            .options(
                selectinload(FarmMembership.user),
                selectinload(FarmMembership.farm),
            )
            .where(
                FarmMembership.farm_id == farm_id,
                FarmMembership.status != "revoked",
            )
            .order_by(FarmMembership.invited_at, FarmMembership.id)
        )
        return list(result.scalars().all())

    async def list_invitations(self, user_id: UUID) -> list[FarmMembership]:
        result = await self.session.execute(
            select(FarmMembership)
            .options(
                selectinload(FarmMembership.user),
                selectinload(FarmMembership.farm),
            )
            .where(
                FarmMembership.user_id == user_id,
                FarmMembership.status == "invited",
            )
            .order_by(FarmMembership.invited_at, FarmMembership.id)
        )
        return list(result.scalars().all())

    async def create(self, membership: FarmMembership) -> FarmMembership:
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def update(self, membership: FarmMembership) -> FarmMembership:
        await self.session.flush()
        return membership

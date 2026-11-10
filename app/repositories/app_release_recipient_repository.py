from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.farm import Farm
from app.models.farm_membership import FarmMembership
from app.models.user import User


class AppReleaseRecipientRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_recipients(
        self,
        *,
        search: str,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int, dict[UUID, list[Farm]]]:
        statement = select(User).where(User.is_active.is_(True))
        if search:
            pattern = f"%{search.strip()}%"
            farm_matches = or_(
                Farm.name.ilike(pattern),
                Farm.phone_number.ilike(pattern),
                Farm.email.ilike(pattern),
            )
            statement = statement.where(
                or_(
                    User.email.ilike(pattern),
                    User.farms.any(farm_matches),
                    User.farm_memberships.any(
                        FarmMembership.farm.has(farm_matches),
                    ),
                )
            )

        count_statement = select(func.count()).select_from(
            statement.order_by(None).subquery()
        )
        total = await self.session.scalar(count_statement)
        users_result = await self.session.scalars(
            statement.order_by(User.email, User.id).offset(offset).limit(limit)
        )
        users = list(users_result.all())
        farms_by_user = await self._farms_for_users([user.id for user in users])
        return users, int(total or 0), farms_by_user

    async def get_recipients(
        self,
        user_ids: list[UUID],
    ) -> tuple[dict[UUID, User], dict[UUID, list[Farm]]]:
        users_result = await self.session.scalars(
            select(User).where(User.id.in_(user_ids), User.is_active.is_(True))
        )
        users = {user.id: user for user in users_result.all()}
        farms_by_user = await self._farms_for_users(list(users))
        return users, farms_by_user

    async def _farms_for_users(
        self,
        user_ids: list[UUID],
    ) -> dict[UUID, list[Farm]]:
        if not user_ids:
            return {}

        rows = await self.session.execute(
            select(Farm.owner_id, Farm)
            .where(Farm.owner_id.in_(user_ids))
            .order_by(Farm.name, Farm.id)
        )
        farms_by_user: dict[UUID, dict[UUID, Farm]] = {
            user_id: {} for user_id in user_ids
        }
        for owner_id, farm in rows:
            farms_by_user[owner_id][farm.id] = farm

        membership_rows = await self.session.execute(
            select(FarmMembership.user_id, Farm)
            .join(Farm, Farm.id == FarmMembership.farm_id)
            .where(
                FarmMembership.user_id.in_(user_ids),
                FarmMembership.status.in_(("active", "invited")),
            )
            .order_by(Farm.name, Farm.id)
        )
        for user_id, farm in membership_rows:
            farms_by_user[user_id][farm.id] = farm

        return {
            user_id: list(farms.values())
            for user_id, farms in farms_by_user.items()
        }

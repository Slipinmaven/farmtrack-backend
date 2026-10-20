from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blocked_device import BlockedDevice
from app.models.user_session import UserSession


class UserSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        await self.session.flush()
        return user_session

    async def get_by_id(self, session_id: UUID) -> UserSession | None:
        result = await self.session.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        limit: int,
        offset: int,
        status: str,
        search: str | None,
    ) -> tuple[list[UserSession], int]:
        filters = [UserSession.user_id == user_id]
        if status == "active":
            filters.append(UserSession.revoked_at.is_(None))
        elif status == "ended":
            filters.append(UserSession.revoked_at.is_not(None))
        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    UserSession.device_name.ilike(pattern),
                    UserSession.platform.ilike(pattern),
                    UserSession.ip_address.ilike(pattern),
                    UserSession.user_agent.ilike(pattern),
                )
            )

        total = await self.session.scalar(
            select(func.count()).select_from(UserSession).where(*filters)
        )
        result = await self.session.execute(
            select(UserSession)
            .where(*filters)
            .order_by(UserSession.created_at.desc(), UserSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def set_last_seen(self, user_session: UserSession, value: datetime) -> None:
        user_session.last_seen_at = value
        await self.session.flush()

    async def revoke(
        self,
        user_session: UserSession,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        if user_session.revoked_at is None:
            user_session.revoked_at = revoked_at
            user_session.revocation_reason = reason
            await self.session.flush()

    async def revoke_for_user(
        self,
        user_id: UUID,
        revoked_at: datetime,
        reason: str,
        except_session_id: UUID | None = None,
    ) -> None:
        query = update(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
        if except_session_id is not None:
            query = query.where(UserSession.id != except_session_id)
        await self.session.execute(
            query.values(revoked_at=revoked_at, revocation_reason=reason)
        )

    async def revoke_for_device(
        self,
        user_id: UUID,
        device_key: str,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        await self.session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.device_key == device_key,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revocation_reason=reason)
        )

    async def get_device_block(
        self,
        user_id: UUID,
        device_key: str,
    ) -> BlockedDevice | None:
        result = await self.session.execute(
            select(BlockedDevice).where(
                BlockedDevice.user_id == user_id,
                BlockedDevice.device_key == device_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_device_block_by_id(
        self,
        user_id: UUID,
        block_id: UUID,
    ) -> BlockedDevice | None:
        result = await self.session.execute(
            select(BlockedDevice).where(
                BlockedDevice.user_id == user_id,
                BlockedDevice.id == block_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_device_blocks(self, user_id: UUID) -> list[BlockedDevice]:
        result = await self.session.execute(
            select(BlockedDevice)
            .where(BlockedDevice.user_id == user_id)
            .order_by(BlockedDevice.updated_at.desc(), BlockedDevice.id.desc())
        )
        return list(result.scalars().all())

    async def save_device_block(self, block: BlockedDevice) -> BlockedDevice:
        self.session.add(block)
        await self.session.flush()
        return block

    async def delete_device_block(self, block: BlockedDevice) -> None:
        await self.session.delete(block)
        await self.session.flush()
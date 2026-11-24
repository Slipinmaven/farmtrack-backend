from datetime import datetime
from uuid import UUID
from sqlalchemy import or_, select, update

from app.models.refresh_token import RefreshToken

class RefreshTokenRepository():
    def __init__(self, session):
        self.session = session

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self.session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def create(self, token: RefreshToken) -> RefreshToken:
        self.session.add(token)
        await self.session.flush() 
        return token

    async def revoke(self, refresh_token: RefreshToken, revoked_at: datetime) -> None:
        refresh_token.revoked_at = revoked_at
        await self.session.flush()

    async def delete(self, refresh_token: RefreshToken) -> None:
        await self.session.delete(refresh_token)
        await self.session.flush()  

    async def revoke_for_session(self, session_id: UUID, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.session_id == session_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_for_user(self, user_id: UUID, revoked_at: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_for_device(
        self,
        user_id: UUID,
        device_key: str,
        revoked_at: datetime,
    ) -> None:
        from app.models.user_session import UserSession

        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.session_id.in_(
                    select(UserSession.id).where(
                        UserSession.user_id == user_id,
                        UserSession.device_key == device_key,
                    )
                ),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_for_user_except_session(
        self,
        user_id: UUID,
        revoked_at: datetime,
        except_session_id: UUID,
    ) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                or_(
                    RefreshToken.session_id.is_(None),
                    RefreshToken.session_id != except_session_id,
                ),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
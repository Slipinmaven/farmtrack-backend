from uuid import UUID
from sqlalchemy import select

from app.models.user import User

class UserRepository():
    def __init__(self, session):
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, user_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_email_for_update(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_deletion_confirmation_hash_for_update(
        self,
        token_hash: str,
    ) -> User | None:
        result = await self.session.execute(
            select(User)
            .where(User.deletion_confirmation_token_hash == token_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush() 
        return user
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.app_release import AppRelease
from app.models.download_token import DownloadToken


class AppReleaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_releases(self) -> list[AppRelease]:
        result = await self.session.execute(
            select(AppRelease).order_by(
                AppRelease.platform,
                AppRelease.version_code.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_release(self, release_id: UUID) -> AppRelease | None:
        return await self.session.get(AppRelease, release_id)

    async def get_by_version_code(self, platform: str, version_code: int) -> AppRelease | None:
        result = await self.session.execute(
            select(AppRelease).where(
                AppRelease.platform == platform,
                AppRelease.version_code == version_code,
            )
        )
        return result.scalar_one_or_none()

    async def clear_latest(self, platform: str) -> None:
        await self.session.execute(
            update(AppRelease)
            .where(AppRelease.platform == platform, AppRelease.is_latest.is_(True))
            .values(is_latest=False)
        )

    async def create_release(self, release: AppRelease) -> AppRelease:
        self.session.add(release)
        await self.session.flush()
        return release


class DownloadTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, token: DownloadToken) -> DownloadToken:
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_by_hash_for_update(self, token_hash: str) -> DownloadToken | None:
        result = await self.session.execute(
            select(DownloadToken)
            .where(DownloadToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, token_id: UUID) -> DownloadToken | None:
        result = await self.session.execute(
            select(DownloadToken)
            .where(DownloadToken.id == token_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_with_release_for_update(self, token_hash: str) -> DownloadToken | None:
        result = await self.session.execute(
            select(DownloadToken)
            .options(selectinload(DownloadToken.release))
            .where(DownloadToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()

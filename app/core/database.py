from collections.abc import AsyncGenerator
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase as SQLAlchemyDeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class Base(SQLAlchemyDeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_recycle=settings.database_pool_recycle,
    pool_pre_ping=settings.database_pool_pre_ping,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
)

async def get_database_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield one request-scoped session and always close it afterward."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@dataclass(frozen=True)
class DatabaseHealth:
    available: bool
    detail: str

async def check_database_health() -> DatabaseHealth:
    """Run a lightweight readiness check without exposing connection details."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return DatabaseHealth(available=True, detail="database connection is available")
    except Exception:
        logger.warning("database_health_check_failed")
        return DatabaseHealth(available=False, detail="database connection is unavailable")


async def dispose_database_engine() -> None:
    """Release all pooled connections during application shutdown."""
    await engine.dispose()

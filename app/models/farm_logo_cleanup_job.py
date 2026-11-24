from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FarmLogoCleanupJob(Base):
    __tablename__ = "farm_logo_cleanup_jobs"
    __table_args__ = (
        Index("ix_farm_logo_cleanup_jobs_available_at", "available_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    logo_path: Mapped[str] = mapped_column(String(512), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

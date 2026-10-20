from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    CheckConstraint, 
    DateTime, 
    ForeignKey, 
    String, 
    Text,
    UniqueConstraint, 
    Uuid, 
    func
)

from app.core.database import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:   
    from app.models.user import User
    from app.models.activities import Activity
    from app.models.blocks import Block
    from app.models.chicken_batches import ChickenBatch
    from app.models.contact import Contact
    from app.models.farm_settings import FarmSettings
    from app.models.products import Product
    from app.models.transactions import Transaction

class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    maximum_chicken_capacity: Mapped[int | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("maximum_chicken_capacity > 0", name="check_maximum_chicken_capacity_positive"),
        UniqueConstraint("owner_id", "name", name="uq_farms_owner_id_name"),
    )

    owner: Mapped["User"] = relationship(
        back_populates="farms",
        lazy="raise",
    )

    farm_settings: Mapped["FarmSettings"] = relationship(
        back_populates="farm",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="farm",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    products: Mapped[list["Product"]] = relationship(
        back_populates="farm",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    blocks: Mapped[list["Block"]] = relationship(
        back_populates="farm",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    chicken_batches: Mapped[list["ChickenBatch"]] = relationship(
        back_populates="farm",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="farm",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="farm", lazy="raise", cascade="all, delete-orphan"
    )
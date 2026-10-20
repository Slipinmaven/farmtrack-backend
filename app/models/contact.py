from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Uuid,
    String,
    Text,
    func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.contact_roles import ContactRole
    from app.models.farm import Farm
    from app.models.transactions import Transaction

class Contact(Base):
    __tablename__= "contacts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    ) 
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    farm: Mapped["Farm"] = relationship(
        back_populates="contacts",
        lazy="raise"
    )
    contact_roles: Mapped[list["ContactRole"]] = relationship(
        back_populates="contact",
        lazy="raise"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="contact", lazy="raise"
    )
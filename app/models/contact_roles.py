from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    Enum as SQLEnum,
    ForeignKey, 
    Uuid, 
    DateTime, 
    UniqueConstraint,
    func
)

from app.core.database import Base
from app.schemas.enums import ContactRoleEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.contact_role_products import ContactRoleProduct

class ContactRole(Base):
    __tablename__ = "contact_roles"
    __table_args__ = (
        UniqueConstraint(
            "contact_id",
            "role",
            name="uq_contact_roles_contact_id_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contact_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("contacts.id"), nullable=False)
    role: Mapped[ContactRoleEnum] = mapped_column(SQLEnum(ContactRoleEnum), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    contact: Mapped["Contact"] = relationship(
        back_populates="contact_roles",
        lazy="raise"
    )
    product_associations: Mapped[list["ContactRoleProduct"]] = relationship(
        back_populates="contact_role",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

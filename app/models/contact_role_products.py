from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.contact_roles import ContactRole
    from app.models.products import Product


class ContactRoleProduct(Base):
    __tablename__ = "contact_role_products"
    __table_args__ = (
        UniqueConstraint(
            "contact_role_id",
            "product_id",
            name="uq_contact_role_products_contact_role_id_product_id",
        ),
        Index("ix_contact_role_products_product_id", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    contact_role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("contact_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    contact_role: Mapped["ContactRole"] = relationship(
        back_populates="product_associations",
        lazy="raise",
    )
    product: Mapped["Product"] = relationship(
        back_populates="contact_role_associations",
        lazy="raise",
    )
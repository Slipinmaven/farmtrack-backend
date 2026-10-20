from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from sqlalchemy import (
    DateTime, 
    Enum as SQLEnum,
    ForeignKey, 
    String, 
    Text,
    Uuid, 
    func
)

from app.core.database import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.schemas.enums import ProductType

if TYPE_CHECKING:
    from app.models.farm import Farm
    from app.models.product_units import ProductUnit
    from app.models.contact_role_products import ContactRoleProduct
    from app.models.transaction_items import TransactionItem

class Product(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    farm_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("farms.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    product_type: Mapped[ProductType] = mapped_column(SQLEnum(ProductType), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    is_sellable: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    farm: Mapped["Farm"] = relationship(
        back_populates="products",
        lazy="raise",
    )
    product_units: Mapped[list["ProductUnit"]] = relationship(
        back_populates="product",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    contact_role_associations: Mapped[list["ContactRoleProduct"]] = relationship(
        back_populates="product",
        lazy="raise",
        passive_deletes=True,
    )
    transaction_items: Mapped[list["TransactionItem"]] = relationship(
        back_populates="product", lazy="raise"
    )

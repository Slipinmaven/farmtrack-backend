from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.models.products import Product
from app.models.units import Unit
from app.repositories.product_repository import ProductRepository
from app.schemas.product import (
    ProductCreateRequest,
    ProductResponse,
    ProductUnitResponse,
    ProductUpdateRequest,
)

app_logger = get_application_logger()


class ProductService:
    def __init__(self, repository: ProductRepository, unit_of_work: UnitOfWork):
        self.repository = repository
        self.unit_of_work = unit_of_work

    async def list_products(
        self,
        farm: Farm,
        search: str | None = None,
    ) -> list[ProductResponse]:
        async with self.unit_of_work:
            products = await self.repository.list_by_farm(farm.id, search)
            return [self._to_response(product) for product in products]

    async def get_product(self, farm: Farm, product_id: UUID) -> ProductResponse:
        async with self.unit_of_work:
            product = await self._get_or_raise(farm.id, product_id)
            return self._to_response(product)

    async def create_product(
        self,
        farm: Farm,
        product_data: ProductCreateRequest,
    ) -> ProductResponse:
        async with self.unit_of_work:
            definitions = [unit.model_dump() for unit in product_data.product_units]
            units = await self._get_units_or_raise(definitions)
            product = await self.repository.create(
                farm.id,
                product_data.model_dump(exclude={"product_units"}),
                self._pair_units_and_definitions(units, definitions),
            )
            await self.unit_of_work.commit()
            app_logger.info(
                "product_created",
                extra={"event": "product_created", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return self._to_response(product)

    async def update_product(
        self,
        farm: Farm,
        product_id: UUID,
        product_data: ProductUpdateRequest,
    ) -> ProductResponse:
        async with self.unit_of_work:
            product = await self.repository.get_by_id_for_update_with_units(
                farm.id,
                product_id,
            )
            if product is None:
                raise ResourceNotFoundError("Product not found.")
            update_data = product_data.model_dump(exclude_unset=True, exclude={"product_units"})
            if (
                "product_type" in update_data
                and update_data["product_type"] != product.product_type
                and await self.repository.has_product_history(product.id)
            ):
                raise ConflictError(
                    "A product type cannot be changed after it has been used in "
                    "inventory, transactions, or related stock records."
                )
            unit_definitions = None
            if "product_units" in product_data.model_fields_set:
                definitions = [unit.model_dump() for unit in product_data.product_units or []]
                existing_units = sorted(
                    (
                        item.unit_id,
                        item.conversion_factor,
                        item.is_base_unit,
                    )
                    for item in product.product_units
                )
                requested_units = sorted(
                    (
                        item["unit_id"],
                        item["conversion_factor"],
                        item["is_base_unit"],
                    )
                    for item in definitions
                )
                if (
                    existing_units != requested_units
                    and await self.repository.has_inventory_movements(
                        farm.id,
                        product.id,
                    )
                ):
                    raise ConflictError(
                        "Product units cannot be changed after stock has been recorded."
                    )
                units = await self._get_units_or_raise(definitions)
                unit_definitions = self._pair_units_and_definitions(units, definitions)
            product = await self.repository.update(product, update_data, unit_definitions)
            await self.unit_of_work.commit()
            app_logger.info(
                "product_updated",
                extra={"event": "product_updated", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return self._to_response(product)

    async def delete_product(self, farm: Farm, product_id: UUID) -> None:
        try:
            async with self.unit_of_work:
                product = await self._get_or_raise(farm.id, product_id)
                await self.repository.delete(product)
                await self.unit_of_work.commit()
        except IntegrityError as exc:
            raise ConflictError(
                "This product is in use and cannot be deleted. Deactivate it instead."
            ) from exc

    async def _get_or_raise(self, farm_id: UUID, product_id: UUID) -> Product:
        product = await self.repository.get_by_id(farm_id, product_id)
        if product is None:
            raise ResourceNotFoundError("Product not found.")
        return product

    async def _get_units_or_raise(self, definitions: list[dict]) -> dict[UUID, Unit]:
        unit_ids = {definition["unit_id"] for definition in definitions}
        units = await self.repository.get_units_by_ids(unit_ids)
        if len(units) != len(unit_ids):
            raise ResourceNotFoundError("One or more units were not found.")
        return units

    @staticmethod
    def _pair_units_and_definitions(
        units: dict[UUID, Unit],
        definitions: list[dict],
    ) -> list[tuple[Unit, dict]]:
        return [(units[definition["unit_id"]], definition) for definition in definitions]

    @staticmethod
    def _to_response(product: Product) -> ProductResponse:
        return ProductResponse(
            id=product.id,
            farm_id=product.farm_id,
            name=product.name,
            product_type=product.product_type,
            description=product.description,
            is_active=product.is_active,
            is_sellable=product.is_sellable,
            created_at=product.created_at,
            updated_at=product.updated_at,
            product_units=[
                ProductUnitResponse(
                    id=product_unit.id,
                    unit_id=product_unit.unit_id,
                    unit_name=product_unit.unit.name,
                    unit_abbreviation=product_unit.unit.abbreviation,
                    conversion_factor=product_unit.conversion_factor,
                    is_base_unit=product_unit.is_base_unit,
                )
                for product_unit in product.product_units
            ],
        )

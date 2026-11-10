from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.block_repository import BlockRepository
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.schemas.egg_collection import (
    EggCollectionCreateRequest,
    EggCollectionResponse,
)
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    InventoryMovementType,
    ProductType,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService

logger = get_application_logger()


class EggCollectionService:
    def __init__(
        self,
        collection_repository: EggCollectionRepository,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        block_repository: BlockRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        inventory_service: InventoryService | None = None,
        farm_repository: FarmRepository | None = None,
    ) -> None:
        self.collection_repository = collection_repository
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.block_repository = block_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.inventory_service = inventory_service
        self.farm_repository = farm_repository

    async def create_collections(
        self,
        farm: Farm,
        request: EggCollectionCreateRequest,
    ) -> list[EggCollectionResponse]:
        async with self.unit_of_work:
            if self.farm_repository is not None:
                locked_farm = await self.farm_repository.get_by_id_for_update(farm.id)
                if locked_farm is None:
                    raise ResourceNotFoundError("Farm not found.")
            products = {}
            blocks = {}
            product_units = {}
            base_units = {}
            records = []
            normalized_totals_by_product: defaultdict[UUID, Decimal] = defaultdict(
                lambda: Decimal("0.000")
            )

            for item in request.items:
                product = products.get(item.product_id)
                if product is None:
                    product = await self.product_repository.get_by_id_for_update(
                        farm.id,
                        item.product_id,
                    )
                    if product is None:
                        raise ResourceNotFoundError(
                            f"Egg product '{item.product_id}' not found for this farm."
                        )
                    if not product.is_active:
                        raise ConflictError(
                            "Eggs cannot be collected against an inactive product."
                        )
                    if product.product_type != ProductType.EGGS:
                        raise ConflictError(
                            "Egg collections require a product of type eggs."
                        )
                    products[item.product_id] = product

                block = blocks.get(item.block_id)
                if block is None:
                    block = await self.block_repository.get_by_id(
                        farm.id,
                        item.block_id,
                    )
                    if block is None:
                        raise ResourceNotFoundError(
                            f"Collection block '{item.block_id}' not found for this farm."
                        )
                    if not block.is_active:
                        raise ConflictError(
                            f"Eggs cannot be collected from inactive block '{block.name}'."
                        )
                    blocks[item.block_id] = block

                unit_key = (product.id, item.unit_id)
                product_unit = product_units.get(unit_key)
                if product_unit is None:
                    product_unit = (
                        await self.product_unit_repository.get_by_product_and_unit(
                            product.id,
                            item.unit_id,
                        )
                    )
                    if product_unit is None:
                        raise ConflictError(
                            f"The selected unit is not configured for egg product "
                            f"'{product.name}'."
                        )
                    product_units[unit_key] = product_unit

                base_unit = base_units.get(product.id)
                if base_unit is None:
                    base_unit = (
                        await self.product_unit_repository.get_base_unit_for_product(
                            product.id
                        )
                    )
                    if base_unit is None:
                        raise ConflictError(
                            f"The base unit is not configured for egg product "
                            f"'{product.name}'."
                        )
                    base_units[product.id] = base_unit

                records.append(
                    {
                        "product_id": product.id,
                        "block_id": block.id,
                        "quantity": item.quantity,
                        "unit_id": product_unit.unit_id,
                        "conversion_factor": product_unit.conversion_factor,
                        "collected_at": request.collected_at,
                        "notes": item.notes,
                        "entry_type": "collection",
                    }
                )
                normalized_totals_by_product[product.id] += (
                    item.quantity * product_unit.conversion_factor
                )

            normalized_totals_by_product = {
                product_id: quantity.quantize(Decimal("0.001"))
                for product_id, quantity in normalized_totals_by_product.items()
            }

            collections = await self.collection_repository.create_many(farm.id, records)
            if self.inventory_service is not None:
                for collection in collections:
                    await self.inventory_service.append_movement(
                        farm_id=farm.id,
                        user_id=farm.owner_id,
                        product_id=collection.product_id,
                        quantity_delta=(
                            collection.quantity * collection.conversion_factor
                        ).quantize(Decimal("0.001")),
                        movement_type=InventoryMovementType.RECEIPT,
                        occurred_on=collection.collected_at.date(),
                        notes=collection.notes or "Egg collection",
                        source_type="egg_collection",
                        source_id=collection.id,
                        source_item_id=collection.id,
                    )
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.EGG_COLLECTION_RECORDED,
                entity_type=ActivityEntityType.EGG_COLLECTION,
                entity_id=collections[0].id,
                details={
                    "collection_ids": [str(collection.id) for collection in collections],
                    "entry_count": len(collections),
                    "collected_at": request.collected_at.isoformat(),
                    "items": [
                        {
                            "product_id": str(item.product_id),
                            "block_id": str(item.block_id),
                            "product_name": products[item.product_id].name,
                            "block_name": blocks[item.block_id].name,
                            "quantity": str(item.quantity),
                            "unit_name": product_units[
                                (item.product_id, item.unit_id)
                            ].unit.name,
                            "unit_abbreviation": product_units[
                                (item.product_id, item.unit_id)
                            ].unit.abbreviation,
                            "quantity_in_base_unit": str(
                                item.quantity
                                * product_units[
                                    (item.product_id, item.unit_id)
                                ].conversion_factor
                            ),
                            "base_unit_name": base_units[
                                item.product_id
                            ].name,
                            "base_unit_abbreviation": base_units[
                                item.product_id
                            ].abbreviation,
                            "notes": item.notes,
                        }
                        for item in request.items
                    ],
                    "quantity_in_base_unit_by_product": {
                        products[product_id].name: str(quantity)
                        for product_id, quantity in normalized_totals_by_product.items()
                    },
                    "base_unit_by_product": {
                        products[product_id].name: base_units[
                            product_id
                        ].name
                        for product_id in normalized_totals_by_product
                    },
                },
            )
            await self.unit_of_work.commit()
            logger.info(
                "egg_collection_batch_recorded",
                extra={
                    "event": "egg_collection_batch_recorded",
                    "farm_id": farm.id,
                    "user_id": farm.owner_id,
                    "collection_ids": [collection.id for collection in collections],
                    "entry_count": len(collections),
                    "quantity_in_base_unit_by_product": {
                        str(product_id): str(quantity)
                        for product_id, quantity in normalized_totals_by_product.items()
                    },
                },
            )
            return [self._to_response(collection) for collection in collections]

    async def list_collections(
        self,
        farm: Farm,
        *,
        product_id: UUID | None = None,
        block_id: UUID | None = None,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
    ) -> list[EggCollectionResponse]:
        for value in (from_datetime, to_datetime):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ConflictError("Collection date filters must include a timezone.")
        if (
            from_datetime is not None
            and to_datetime is not None
            and from_datetime > to_datetime
        ):
            raise ConflictError("from_datetime must be on or before to_datetime.")
        async with self.unit_of_work:
            collections = await self.collection_repository.list_by_farm(
                farm.id,
                product_id=product_id,
                block_id=block_id,
                from_datetime=from_datetime,
                to_datetime=to_datetime,
            )
            return [self._to_response(collection) for collection in collections]

    @staticmethod
    def _to_response(collection) -> EggCollectionResponse:
        return EggCollectionResponse(
            id=collection.id,
            farm_id=collection.farm_id,
            product_id=collection.product_id,
            block_id=collection.block_id,
            quantity=collection.quantity,
            unit_id=collection.unit_id,
            conversion_factor=collection.conversion_factor,
            quantity_in_base_unit=(
                collection.quantity * collection.conversion_factor
            ).quantize(Decimal("0.001")),
            collected_at=collection.collected_at,
            entry_type=collection.entry_type,
            notes=collection.notes,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
        )
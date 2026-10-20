from datetime import datetime, time, timezone
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.inventory_opening_setup_repository import (
    InventoryOpeningSetupRepository,
)
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    InventoryMovementType,
    ProductType,
)
from app.schemas.inventory_opening_setup import (
    InventoryOpeningSetupRequest,
    InventoryOpeningSetupResponse,
    InventoryOpeningSetupSpeciesStatus,
    InventoryOpeningSetupStatusResponse,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService


class InventoryOpeningSetupService:
    def __init__(
        self,
        *,
        farm_repository: FarmRepository,
        setup_repository: InventoryOpeningSetupRepository,
        batch_repository: ChickenBatchRepository,
        batch_block_repository: BatchBlockRepository,
        block_repository: BlockRepository,
        collection_repository: EggCollectionRepository,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        inventory_service: InventoryService,
        activity_service: ActivityService,
        unit_of_work: UnitOfWork,
    ):
        self.farm_repository = farm_repository
        self.setup_repository = setup_repository
        self.batch_repository = batch_repository
        self.batch_block_repository = batch_block_repository
        self.block_repository = block_repository
        self.collection_repository = collection_repository
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.inventory_service = inventory_service
        self.activity_service = activity_service
        self.unit_of_work = unit_of_work

    async def get_status(
        self,
        farm: Farm,
    ) -> InventoryOpeningSetupStatusResponse:
        async with self.unit_of_work:
            chicken_setup = await self.setup_repository.get_for_species(
                farm.id, "chickens"
            )
            egg_setup = await self.setup_repository.get_for_species(farm.id, "eggs")
            batches = await self.batch_repository.list_by_farm(farm.id)
            collections = await self.collection_repository.list_by_farm(farm.id)
            products = await self.product_repository.list_by_farm(farm.id)
            has_chicken_ledger = False
            has_egg_ledger = False
            for product in products:
                if product.product_type not in (
                    ProductType.CHICKENS,
                    ProductType.EGGS,
                ):
                    continue
                has_movements = await self.product_repository.has_inventory_movements(
                    farm.id, product.id
                )
                if product.product_type == ProductType.CHICKENS:
                    has_chicken_ledger = has_chicken_ledger or has_movements
                else:
                    has_egg_ledger = has_egg_ledger or has_movements
            return InventoryOpeningSetupStatusResponse(
                chickens=InventoryOpeningSetupSpeciesStatus(
                    eligible=(
                        chicken_setup is None and not batches and not has_chicken_ledger
                    ),
                    completed_at=chicken_setup.setup_date if chicken_setup else None,
                ),
                eggs=InventoryOpeningSetupSpeciesStatus(
                    eligible=(
                        egg_setup is None
                        and not collections
                        and not has_egg_ledger
                    ),
                    completed_at=egg_setup.setup_date if egg_setup else None,
                ),
            )

    async def create(
        self,
        farm: Farm,
        request: InventoryOpeningSetupRequest,
    ) -> InventoryOpeningSetupResponse:
        species = request.species
        async with self.unit_of_work:
            locked_farm = await self.farm_repository.get_by_id_for_update(farm.id)
            if locked_farm is None:
                raise ResourceNotFoundError("Farm not found.")
            if await self.setup_repository.get_for_species(farm.id, species):
                raise ConflictError(f"Opening {species} stock has already been recorded.")

            if species == "chickens":
                products = await self.product_repository.list_by_farm(farm.id)
                has_chicken_activity = False
                for product in products:
                    if product.product_type != ProductType.CHICKENS:
                        continue
                    has_movements = (
                        await self.product_repository.has_inventory_movements(
                            farm.id, product.id
                        )
                    )
                    if has_movements:
                        has_chicken_activity = True
                        break
                if has_chicken_activity:
                    raise ConflictError(
                        "Opening chicken stock is only available before chicken inventory activity exists."
                    )
                if request.egg_stock or not request.chicken_batches:
                    raise ConflictError(
                        "Chicken setup requires at least one batch and cannot include egg stock."
                    )
                await self._create_chicken_batches(farm, request)
                record_count = len(request.chicken_batches)
            else:
                if request.chicken_batches or not request.egg_stock:
                    raise ConflictError(
                        "Egg setup requires at least one egg stock entry and cannot include chicken batches."
                    )
                products = await self.product_repository.list_by_farm(farm.id)
                for product in products:
                    if (
                        product.product_type == ProductType.EGGS
                        and await self.product_repository.has_inventory_movements(
                            farm.id, product.id
                        )
                    ):
                        raise ConflictError(
                            "Opening egg stock is only available before egg inventory activity exists."
                        )
                await self._create_egg_stock(farm, request)
                record_count = len(request.egg_stock)

            setup = await self.setup_repository.create(
                farm.id, species, request.setup_date
            )
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.INVENTORY_OPENING_STOCK_RECORDED,
                entity_type=ActivityEntityType.INVENTORY_OPENING_SETUP,
                entity_id=setup.id,
                details={
                    "action": "opening_stock_setup",
                    "species": species,
                    "setup_date": request.setup_date.isoformat(),
                    "record_count": record_count,
                },
            )
            await self.unit_of_work.commit()
            return InventoryOpeningSetupResponse(
                species=species,
                setup_date=request.setup_date,
                record_count=record_count,
            )

    async def _create_chicken_batches(
        self,
        farm: Farm,
        request: InventoryOpeningSetupRequest,
    ) -> None:
        if await self.batch_repository.list_by_farm(farm.id):
            raise ConflictError(
                "Opening chicken stock is only available before any chicken batches exist."
            )

        used_names: set[str] = set()
        block_totals: dict[UUID, int] = {}
        blocks = {}
        chicken_products = [
            product
            for product in await self.product_repository.list_by_farm(farm.id)
            if product.product_type == ProductType.CHICKENS and product.is_active
        ]
        for batch in request.chicken_batches:
            if batch.hatch_date is not None and batch.hatch_date > request.setup_date:
                raise ConflictError(
                    f"Hatch date for batch '{batch.name}' cannot be after the opening stock date."
                )
            key = batch.name.casefold()
            if key in used_names:
                raise ConflictError("Chicken batch names must be unique.")
            used_names.add(key)
            allocated_blocks: set[UUID] = set()
            for allocation in batch.allocations:
                if allocation.block_id in allocated_blocks:
                    raise ConflictError(
                        "A chicken batch can only have one allocation per housing block."
                    )
                allocated_blocks.add(allocation.block_id)
                block = blocks.get(allocation.block_id)
                if block is None:
                    block = await self.block_repository.get_by_id_for_update(
                        farm.id, allocation.block_id
                    )
                    if block is None:
                        raise ResourceNotFoundError(
                            f"Housing block '{allocation.block_id}' not found for this farm."
                        )
                    if not block.is_active:
                        raise ConflictError(
                            f"Opening chickens cannot be placed in inactive block '{block.name}'."
                        )
                    blocks[allocation.block_id] = block
                block_totals[allocation.block_id] = (
                    block_totals.get(allocation.block_id, 0) + allocation.quantity
                )

        for block_id, quantity in block_totals.items():
            block = blocks[block_id]
            occupied = await self.block_repository.get_occupied_chickens(
                farm.id, block_id
            )
            if occupied + quantity > block.capacity + block.over_capacity_limit:
                raise ConflictError(
                    f"Opening stock would exceed the capacity limit for block '{block.name}'."
                )

        for batch in request.chicken_batches:
            chicken_batch = await self.batch_repository.create(
                farm.id,
                {
                    "name": batch.name,
                    "chicken_type": batch.chicken_type,
                    "breed": batch.breed,
                    "hatch_date": batch.hatch_date,
                    "status": ChickenBatchStatus.ACTIVE,
                    "is_opening_stock": True,
                    "notes": "Opening stock",
                },
            )
            for allocation in batch.allocations:
                await self.batch_block_repository.create(
                    {
                        "batch_id": chicken_batch.id,
                        "block_id": allocation.block_id,
                        "quantity": allocation.quantity,
                    }
                )
            if chicken_products:
                await self.inventory_service.append_movement(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    product_id=chicken_products[0].id,
                    quantity_delta=Decimal(
                        sum(allocation.quantity for allocation in batch.allocations)
                    ),
                    movement_type=InventoryMovementType.OPENING_BALANCE,
                    occurred_on=request.setup_date,
                    notes=f"Opening chicken stock: {batch.name}",
                    source_type="chicken_opening_batch",
                    source_id=chicken_batch.id,
                    source_item_id=chicken_batch.id,
                    unit_cost=batch.unit_cost,
                )

    async def _create_egg_stock(self, farm: Farm, request) -> None:
        if await self.collection_repository.list_by_farm(farm.id):
            raise ConflictError(
                "Opening egg stock is only available before any egg collections exist."
            )
        products = {}
        units = {}
        records = []
        collected_at = datetime.combine(
            request.setup_date,
            time(hour=12),
            tzinfo=timezone.utc,
        )

        for item in request.egg_stock:
            product = products.get(item.product_id)
            if product is None:
                product = await self.product_repository.get_by_id_for_update(
                    farm.id, item.product_id
                )
                if product is None:
                    raise ResourceNotFoundError(
                        f"Egg product '{item.product_id}' not found for this farm."
                    )
                if not product.is_active or product.product_type != ProductType.EGGS:
                    raise ConflictError(
                        "Opening egg stock requires an active egg product."
                    )
                if await self.product_repository.has_inventory_movements(
                    farm.id, product.id
                ):
                    raise ConflictError(
                        f"Opening stock is unavailable because '{product.name}' already has inventory activity."
                    )
                products[item.product_id] = product

            unit_key = (item.product_id, item.unit_id)
            product_unit = units.get(unit_key)
            if product_unit is None:
                product_unit = (
                    await self.product_unit_repository.get_by_product_and_unit(
                        item.product_id, item.unit_id
                    )
                )
                if product_unit is None:
                    raise ConflictError(
                        f"The selected unit is not configured for egg product '{product.name}'."
                    )
                units[unit_key] = product_unit

            records.append(
                {
                    "product_id": product.id,
                    "block_id": item.block_id,
                    "quantity": item.quantity,
                    "unit_id": product_unit.unit_id,
                    "conversion_factor": product_unit.conversion_factor,
                    "collected_at": collected_at,
                    "notes": "Opening stock",
                    "entry_type": "opening_stock",
                }
            )

        collections = await self.collection_repository.create_many(farm.id, records)
        for collection, opening_item in zip(collections, request.egg_stock, strict=True):
            await self.inventory_service.append_movement(
                farm_id=farm.id,
                user_id=farm.owner_id,
                product_id=collection.product_id,
                quantity_delta=(
                    collection.quantity * collection.conversion_factor
                ).quantize(Decimal("0.001")),
                movement_type=InventoryMovementType.OPENING_BALANCE,
                occurred_on=request.setup_date,
                notes="Opening egg stock",
                source_type="egg_collection",
                source_id=collection.id,
                source_item_id=collection.id,
                unit_cost=(
                    opening_item.unit_cost / units[
                        (opening_item.product_id, opening_item.unit_id)
                    ].conversion_factor
                    if opening_item.unit_cost is not None
                    else None
                ),
            )

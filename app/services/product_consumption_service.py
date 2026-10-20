from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.product_consumption_repository import ProductConsumptionRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    InventoryMovementType,
    ProductType,
)
from app.schemas.product_consumption import (
    ProductConsumptionAllocationRequest,
    ProductConsumptionBatchCreateRequest,
    ProductConsumptionCreateRequest,
    ProductConsumptionResponse,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService

logger = get_application_logger()


class ProductConsumptionService:
    def __init__(
        self,
        consumption_repository: ProductConsumptionRepository,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        block_repository: BlockRepository,
        chicken_batch_repository: ChickenBatchRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        inventory_service: InventoryService | None = None,
    ) -> None:
        self.consumption_repository = consumption_repository
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.block_repository = block_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.inventory_service = inventory_service

    async def record_consumption(
        self,
        farm: Farm,
        request: ProductConsumptionCreateRequest,
    ) -> ProductConsumptionResponse:
        records = await self.record_consumptions(
            farm,
            ProductConsumptionBatchCreateRequest(
                product_id=request.product_id,
                unit_id=request.unit_id,
                allocations=[
                    ProductConsumptionAllocationRequest(
                        quantity=request.quantity,
                        block_id=request.block_id,
                        batch_id=request.batch_id,
                    )
                ],
                consumption_date=request.consumption_date,
                notes=request.notes,
            ),
        )
        return records[0]

    async def record_consumptions(
        self,
        farm: Farm,
        request: ProductConsumptionBatchCreateRequest,
    ) -> list[ProductConsumptionResponse]:
        async with self.unit_of_work:
            product = await self.product_repository.get_by_id(
                farm.id,
                request.product_id,
            )
            if product is None:
                raise ResourceNotFoundError("Product not found for this farm.")
            if product.product_type in {ProductType.CHICKENS, ProductType.EGGS}:
                raise ConflictError(
                    "Chicken and egg stock must be updated through their dedicated "
                    "flock and egg records."
                )
            if not product.is_active:
                raise ConflictError("Consumption cannot be recorded for an inactive product.")

            product_unit = await self.product_unit_repository.get_by_product_and_unit(
                product.id,
                request.unit_id,
            )
            if product_unit is None:
                raise ConflictError(
                    "The selected unit is not configured for this product."
                )
            base_unit = (
                await self.product_unit_repository.get_base_unit_for_product(
                    product.id
                )
            )
            if base_unit is None:
                raise ConflictError(
                    f"The base unit is not configured for product '{product.name}'."
                )

            total_quantity = sum(
                (allocation.quantity for allocation in request.allocations),
                Decimal("0"),
            )
            if total_quantity <= 0:
                raise ConflictError("Consumption quantity must be greater than zero.")

            records: list[ProductConsumptionResponse] = []
            for allocation in request.allocations:
                block = None
                if allocation.block_id is not None:
                    block = await self.block_repository.get_by_id(
                        farm.id,
                        allocation.block_id,
                    )
                    if block is None:
                        raise ResourceNotFoundError(
                            "Consumption block not found for this farm."
                        )

                batch = None
                if allocation.batch_id is not None:
                    batch = await self.chicken_batch_repository.get_by_id(
                        farm.id,
                        allocation.batch_id,
                    )
                    if batch is None:
                        raise ResourceNotFoundError(
                            "Consumption batch not found for this farm."
                        )

                if allocation.block_id is not None and allocation.batch_id is not None:
                    assignment = (
                        await self.batch_block_repository.get_by_batch_and_block(
                            allocation.batch_id,
                            allocation.block_id,
                        )
                    )
                    if assignment is None:
                        raise ConflictError(
                            "The selected chicken batch is not assigned to the selected block."
                        )

                consumption = await self.consumption_repository.create(
                    farm.id,
                    {
                        "product_id": product.id,
                        "unit_id": product_unit.unit_id,
                        "quantity": allocation.quantity,
                        "conversion_factor": product_unit.conversion_factor,
                        "block_id": allocation.block_id,
                        "batch_id": allocation.batch_id,
                        "consumption_date": request.consumption_date,
                        "notes": request.notes,
                    },
                )
                base_quantity = (
                    consumption.quantity * consumption.conversion_factor
                ).quantize(Decimal("0.001"))
                if self.inventory_service is not None:
                    await self.inventory_service.append_movement(
                        farm_id=farm.id,
                        user_id=farm.owner_id,
                        product_id=product.id,
                        quantity_delta=-base_quantity,
                        movement_type=InventoryMovementType.CONSUMPTION,
                        occurred_on=consumption.consumption_date,
                        notes=consumption.notes or "Product consumption",
                        source_type="product_consumption",
                        source_id=consumption.id,
                        source_item_id=consumption.id,
                    )
                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    activity_type=ActivityType.PRODUCT_CONSUMPTION_RECORDED,
                    entity_type=ActivityEntityType.PRODUCT_CONSUMPTION,
                    entity_id=consumption.id,
                    details={
                        "product_id": str(consumption.product_id),
                        "product_name": product.name,
                        "quantity": str(consumption.quantity),
                        "unit_id": str(consumption.unit_id),
                        "unit_name": product_unit.unit.name,
                        "unit_abbreviation": product_unit.unit.abbreviation,
                        "quantity_in_base_unit": str(base_quantity),
                        "base_unit_name": base_unit.name,
                        "base_unit_abbreviation": base_unit.abbreviation,
                        "consumption_date": consumption.consumption_date.isoformat(),
                        "notes": consumption.notes,
                        "block_name": block.name if block is not None else None,
                        "batch_name": batch.name if batch is not None else None,
                        "block_id": (
                            str(consumption.block_id)
                            if consumption.block_id is not None
                            else None
                        ),
                        "batch_id": (
                            str(consumption.batch_id)
                            if consumption.batch_id is not None
                            else None
                        ),
                    },
                )
                records.append(self._to_response(consumption))
            await self.unit_of_work.commit()
            logger.info(
                "product_consumption_recorded",
                extra={
                    "event": "product_consumption_recorded",
                    "farm_id": farm.id,
                    "user_id": farm.owner_id,
                    "consumption_ids": [record.id for record in records],
                    "product_id": product.id,
                    "quantity": str(total_quantity),
                },
            )
            return records

    async def list_consumptions(
        self,
        farm: Farm,
        *,
        product_id: UUID | None = None,
        block_id: UUID | None = None,
        batch_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ProductConsumptionResponse]:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ConflictError("from_date must be on or before to_date.")
        async with self.unit_of_work:
            rows = await self.consumption_repository.list_by_farm(
                farm.id,
                product_id=product_id,
                block_id=block_id,
                batch_id=batch_id,
                from_date=from_date,
                to_date=to_date,
            )
            return [self._to_response(row) for row in rows]

    @staticmethod
    def _to_response(row) -> ProductConsumptionResponse:
        return ProductConsumptionResponse(
            id=row.id,
            farm_id=row.farm_id,
            product_id=row.product_id,
            unit_id=row.unit_id,
            quantity=row.quantity,
            conversion_factor=row.conversion_factor,
            quantity_in_base_unit=(row.quantity * row.conversion_factor).quantize(
                Decimal("0.001")
            ),
            block_id=row.block_id,
            batch_id=row.batch_id,
            consumption_date=row.consumption_date,
            notes=row.notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
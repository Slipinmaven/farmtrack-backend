from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.inventory_movement_repository import (
    InventoryMovementRepository,
)
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    InventoryMovementType,
    ProductType,
)
from app.schemas.inventory import (
    InventoryAdjustmentRequest,
    InventoryMovementResponse,
    InventoryOverviewResponse,
    InventoryProductBalance,
)
from app.services.activity_service import ActivityService


class InventoryService:
    def __init__(
        self,
        movement_repository: InventoryMovementRepository,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
    ) -> None:
        self.movement_repository = movement_repository
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service

    async def get_overview(
        self,
        farm: Farm,
        *,
        product_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> InventoryOverviewResponse:
        async with self.unit_of_work:
            balances = await self.movement_repository.list_balances(farm.id)
            movements = await self.movement_repository.list_movements(
                farm.id,
                product_id=product_id,
                limit=limit,
                offset=offset,
            )
            return InventoryOverviewResponse(
                items=[
                    InventoryProductBalance(
                        product_id=product_id,
                        product_name=product_name,
                        product_type=product_type,
                        quantity=quantity,
                        unit_name=unit_name,
                        unit_abbreviation=unit_abbreviation,
                    )
                    for (
                        product_id,
                        product_name,
                        product_type,
                        quantity,
                        unit_name,
                        unit_abbreviation,
                    ) in balances
                ],
                movements=[
                    InventoryMovementResponse(
                        id=movement.id,
                        product_id=product.id,
                        product_name=product.name,
                        product_type=product.product_type,
                        quantity_delta=movement.quantity_delta,
                        unit_name=unit.name,
                        unit_abbreviation=unit.abbreviation,
                        movement_type=movement.movement_type,
                        source_type=movement.source_type,
                        source_id=movement.source_id,
                        source_item_id=movement.source_item_id,
                        unit_cost=movement.unit_cost,
                        occurred_on=movement.occurred_on,
                        notes=movement.notes,
                        created_at=movement.created_at,
                    )
                    for movement, product, unit in movements
                ],
            )

    async def record_opening_balance(
        self,
        farm: Farm,
        request: InventoryAdjustmentRequest,
    ) -> InventoryMovementResponse:
        return await self._record_manual_movement(
            farm,
            request,
            InventoryMovementType.OPENING_BALANCE,
            opening=True,
        )

    async def record_adjustment(
        self,
        farm: Farm,
        request: InventoryAdjustmentRequest,
    ) -> InventoryMovementResponse:
        return await self._record_manual_movement(
            farm,
            request,
            InventoryMovementType.ADJUSTMENT,
            opening=False,
        )

    async def append_movement(
        self,
        *,
        farm_id: UUID,
        user_id: UUID | None,
        product_id: UUID,
        quantity_delta: Decimal,
        movement_type: InventoryMovementType,
        occurred_on: date,
        notes: str,
        source_type: str,
        source_id: UUID,
        source_item_id: UUID,
        unit_cost: Decimal | None = None,
    ) -> None:
        product = await self.product_repository.get_by_id_for_update(
            farm_id,
            product_id,
        )
        if product is None:
            raise ResourceNotFoundError("Inventory product not found for this farm.")
        base_unit = await self.product_unit_repository.get_base_unit_for_product(
            product_id
        )
        if base_unit is None:
            raise ConflictError(
                f"The base unit is not configured for product '{product.name}'."
            )
        current_quantity = await self.movement_repository.get_balance(
            farm_id,
            product_id,
        )
        if current_quantity + quantity_delta < 0:
            raise ConflictError(
                f"Not enough {product.name} in stock. "
                f"{current_quantity} {base_unit.name} is available."
            )
        if quantity_delta < 0:
            unit_cost = await self._weighted_average_cost(
                farm_id,
                product_id,
                occurred_on,
            )
        await self.movement_repository.create(
            farm_id=farm_id,
            user_id=user_id,
            product_id=product_id,
            unit_id=base_unit.id,
            quantity_delta=quantity_delta,
            movement_type=movement_type,
            occurred_on=occurred_on,
            notes=notes,
            source_type=source_type,
            source_id=source_id,
            source_item_id=source_item_id,
            unit_cost=unit_cost,
        )

    async def _weighted_average_cost(
        self,
        farm_id: UUID,
        product_id: UUID,
        occurred_on: date,
    ) -> Decimal | None:
        movements = await self.movement_repository.list_product_cost_movements(
            farm_id,
            product_id,
            as_of=occurred_on,
        )
        quantity = Decimal("0")
        value = Decimal("0")
        unvalued_quantity = Decimal("0")
        for movement in movements:
            delta = Decimal(movement.quantity_delta)
            movement_type = getattr(movement.movement_type, "value", movement.movement_type)
            if movement_type == InventoryMovementType.VALUATION.value:
                if movement.unit_cost is None:
                    raise ConflictError(
                        "A stock valuation movement is missing its unit cost."
                    )
                quantity += unvalued_quantity
                value += unvalued_quantity * Decimal(movement.unit_cost)
                unvalued_quantity = Decimal("0")
                continue
            if delta > 0:
                if movement.unit_cost is None:
                    unvalued_quantity += delta
                else:
                    quantity += delta
                    value += delta * Decimal(movement.unit_cost)
            else:
                removed = -delta
                if unvalued_quantity:
                    unvalued_removed = min(unvalued_quantity, removed)
                    unvalued_quantity -= unvalued_removed
                    removed -= unvalued_removed
                if removed and quantity:
                    average = value / quantity
                    valued_removed = min(quantity, removed)
                    quantity -= valued_removed
                    value -= average * valued_removed
        if unvalued_quantity > 0 or quantity <= 0:
            return None
        return value / quantity

    async def _record_manual_movement(
        self,
        farm: Farm,
        request: InventoryAdjustmentRequest,
        movement_type: InventoryMovementType,
        *,
        opening: bool,
    ) -> InventoryMovementResponse:
        async with self.unit_of_work:
            product = await self.product_repository.get_by_id_for_update(
                farm.id,
                request.product_id,
            )
            if product is None:
                raise ResourceNotFoundError("Inventory product not found for this farm.")
            if product.product_type in {ProductType.CHICKENS, ProductType.EGGS}:
                raise ConflictError(
                    "Chicken and egg stock cannot be changed through generic "
                    "inventory adjustments. Use flock or egg activity records "
                    "so batch, block, and collection history stays accurate."
                )
            product_unit = await self.product_unit_repository.get_by_product_and_unit(
                product.id,
                request.unit_id,
            )
            if product_unit is None:
                raise ConflictError(
                    "The selected unit is not configured for this product."
                )
            base_unit = await self.product_unit_repository.get_base_unit_for_product(
                product.id
            )
            if base_unit is None:
                raise ConflictError(
                    f"The base unit is not configured for product '{product.name}'."
                )
            if opening and await self.movement_repository.has_movements(
                farm.id,
                product.id,
            ):
                raise ConflictError(
                    "Opening stock can only be recorded once, before other stock movements."
                )

            quantity = (
                request.quantity * product_unit.conversion_factor
            ).quantize(Decimal("0.001"))
            if quantity <= 0:
                raise ConflictError(
                    "The entered quantity is too small to represent in the base unit."
                )
            delta = quantity if request.direction == "in" else -quantity
            current_quantity = await self.movement_repository.get_balance(
                farm.id,
                product.id,
            )
            if current_quantity + delta < 0:
                raise ConflictError(
                    f"Not enough {product.name} in stock. "
                    f"{current_quantity} {base_unit.name} is available."
                )
            movement = await self.movement_repository.create(
                farm_id=farm.id,
                user_id=farm.owner_id,
                product_id=product.id,
                unit_id=base_unit.id,
                quantity_delta=delta,
                movement_type=movement_type,
                occurred_on=request.occurred_on,
                notes=request.reason,
                unit_cost=(
                    request.unit_cost / product_unit.conversion_factor
                    if delta > 0 and request.unit_cost is not None
                    else await self._weighted_average_cost(
                        farm.id,
                        product.id,
                        request.occurred_on,
                    )
                    if delta < 0
                    else None
                ),
            )
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.INVENTORY_ADJUSTED,
                entity_type=ActivityEntityType.INVENTORY_MOVEMENT,
                entity_id=movement.id,
                details={
                    "product_id": str(product.id),
                    "product_name": product.name,
                    "movement_type": movement_type.value,
                    "quantity": str(quantity),
                    "unit_name": base_unit.name,
                    "direction": request.direction,
                    "occurred_on": request.occurred_on.isoformat(),
                    "reason": request.reason,
                },
            )
            await self.unit_of_work.commit()
            return InventoryMovementResponse(
                id=movement.id,
                product_id=product.id,
                product_name=product.name,
                product_type=product.product_type,
                quantity_delta=movement.quantity_delta,
                unit_name=base_unit.name,
                unit_abbreviation=base_unit.abbreviation,
                movement_type=movement_type,
                source_type=None,
                source_id=None,
                source_item_id=None,
                unit_cost=movement.unit_cost,
                occurred_on=movement.occurred_on,
                notes=movement.notes,
                created_at=movement.created_at,
            )

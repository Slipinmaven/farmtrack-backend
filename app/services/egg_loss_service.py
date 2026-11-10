from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.egg_collection_repository import EggCollectionRepository
from app.repositories.egg_loss_repository import EggLossRepository
from app.repositories.inventory_movement_repository import (
    InventoryMovementRepository,
)
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.repositories.transaction_item_repository import TransactionItemRepository
from app.schemas.egg_loss import (
    EggLossBatchItemRequest,
    EggLossBatchCreateRequest,
    EggLossCreateRequest,
    EggLossResponse,
)
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    EggLossReason,
    InventoryMovementType,
    ProductType,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService

logger = get_application_logger()


class EggLossService:
    def __init__(
        self,
        loss_repository: EggLossRepository,
        collection_repository: EggCollectionRepository,
        product_repository: ProductRepository,
        product_unit_repository: ProductUnitRepository,
        transaction_item_repository: TransactionItemRepository,
        inventory_movement_repository: InventoryMovementRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        inventory_service: InventoryService | None = None,
    ) -> None:
        self.loss_repository = loss_repository
        self.collection_repository = collection_repository
        self.product_repository = product_repository
        self.product_unit_repository = product_unit_repository
        self.transaction_item_repository = transaction_item_repository
        self.inventory_movement_repository = inventory_movement_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.inventory_service = inventory_service

    async def create_loss(
        self,
        farm: Farm,
        request: EggLossCreateRequest,
    ) -> EggLossResponse:
        losses = await self.create_batch_loss(
            farm,
            EggLossBatchCreateRequest(
                product_id=request.product_id,
                loss_date=request.loss_date,
                reason=request.reason,
                items=[
                    EggLossBatchItemRequest(
                        quantity=request.quantity,
                        unit_id=request.unit_id,
                    )
                ],
                notes=request.notes,
            ),
        )
        return losses[0]

    async def create_batch_loss(
        self,
        farm: Farm,
        request: EggLossBatchCreateRequest,
    ) -> list[EggLossResponse]:
        async with self.unit_of_work:
            product = await self.product_repository.get_by_id_for_update(
                farm.id,
                request.product_id,
            )
            if product is None:
                raise ResourceNotFoundError("Egg product not found for this farm.")
            if not product.is_active:
                raise ConflictError("Egg losses cannot be recorded for an inactive product.")
            if product.product_type != ProductType.EGGS:
                raise ConflictError("Egg losses require a product of type eggs.")

            normalized_items = []
            loss_quantity = Decimal("0.000")
            for item in request.items:
                product_unit = (
                    await self.product_unit_repository.get_by_product_and_unit(
                        product.id,
                        item.unit_id,
                    )
                )
                if product_unit is None:
                    raise ConflictError(
                        "A selected unit is not configured for this egg product."
                    )
                normalized_quantity = item.quantity * product_unit.conversion_factor
                loss_quantity += normalized_quantity
                normalized_items.append((item, product_unit, normalized_quantity))

            base_unit = (
                await self.product_unit_repository.get_base_unit_for_product(
                    product.id
                )
            )
            if base_unit is None:
                raise ConflictError(
                    f"The base unit is not configured for egg product '{product.name}'."
                )

            collected_quantity = await self.collection_repository.get_total_base_quantity(
                farm.id,
                product.id,
            )
            previously_lost = await self.loss_repository.get_total_base_quantity(
                farm.id,
                product.id,
            )
            previously_sold = (
                await self.transaction_item_repository.get_sold_base_quantity(
                    farm.id,
                    product.id,
                )
            )
            settlement_received_totals = (
                await self.inventory_movement_repository.get_totals_by_type(
                    farm.id,
                    InventoryMovementType.SETTLEMENT_RECEIVED,
                )
            )
            settlement_issued_totals = (
                await self.inventory_movement_repository.get_totals_by_type(
                    farm.id,
                    InventoryMovementType.SETTLEMENT_ISSUED,
                )
            )
            available_quantity = max(
                collected_quantity
                - previously_lost
                - previously_sold
                + settlement_received_totals.get(product.id, Decimal("0.000"))
                + settlement_issued_totals.get(product.id, Decimal("0.000")),
                Decimal("0.000"),
            )
            if loss_quantity > available_quantity:
                raise ConflictError(
                    f"Cannot record this egg loss: requested loss is "
                    f"{loss_quantity} base units, but only {available_quantity} "
                    "base units remain in farm inventory for this product."
                )

            losses = [
                await self.loss_repository.create(
                    farm.id,
                    {
                        "product_id": product.id,
                        "quantity": item.quantity,
                        "unit_id": product_unit.unit_id,
                        "conversion_factor": product_unit.conversion_factor,
                        "loss_date": request.loss_date,
                        "reason": request.reason,
                        "notes": request.notes,
                    },
                )
                for item, product_unit, _ in normalized_items
            ]
            if self.inventory_service is not None:
                for loss, (_, _, base_quantity) in zip(
                    losses,
                    normalized_items,
                    strict=True,
                ):
                    await self.inventory_service.append_movement(
                        farm_id=farm.id,
                        user_id=farm.owner_id,
                        product_id=product.id,
                        quantity_delta=-base_quantity.quantize(Decimal("0.001")),
                        movement_type=InventoryMovementType.LOSS,
                        occurred_on=request.loss_date,
                        notes=loss.notes or f"Egg loss: {request.reason.value}",
                        source_type="egg_loss",
                        source_id=loss.id,
                        source_item_id=loss.id,
                    )
            remaining_quantity = available_quantity - loss_quantity
            total_loss_ids = [str(loss.id) for loss in losses]
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.EGG_LOSS_RECORDED,
                entity_type=ActivityEntityType.EGG_LOSS,
                entity_id=losses[0].id,
                details={
                    "loss_ids": total_loss_ids,
                    "entry_count": len(losses),
                    "product_name": product.name,
                    "product_id": str(product.id),
                    "loss_date": request.loss_date.isoformat(),
                    "reason": request.reason.value,
                    "quantity_in_base_unit": str(loss_quantity),
                    "base_unit_name": base_unit.name,
                    "base_unit_abbreviation": base_unit.abbreviation,
                    "remaining_inventory_in_base_unit": str(remaining_quantity),
                    "notes": request.notes,
                    "items": [
                        {
                            "quantity": str(item.quantity),
                            "unit_name": product_unit.unit.name,
                            "unit_abbreviation": product_unit.unit.abbreviation,
                            "quantity_in_base_unit": str(quantity),
                            "base_unit_name": base_unit.name,
                            "base_unit_abbreviation": base_unit.abbreviation,
                        }
                        for item, product_unit, quantity in normalized_items
                    ],
                },
            )
            await self.unit_of_work.commit()
            logger.info(
                "egg_loss_recorded",
                extra={
                    "event": "egg_loss_recorded",
                    "farm_id": farm.id,
                    "user_id": farm.owner_id,
                    "loss_ids": [loss.id for loss in losses],
                    "product_id": product.id,
                    "quantity_in_base_unit": str(loss_quantity),
                    "remaining_inventory_in_base_unit": str(remaining_quantity),
                    "reason": request.reason.value,
                },
            )
            return [self._to_response(loss) for loss in losses]

    async def list_losses(
        self,
        farm: Farm,
        *,
        product_id: UUID | None = None,
        reason: EggLossReason | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[EggLossResponse]:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ConflictError("from_date must be on or before to_date.")
        async with self.unit_of_work:
            losses = await self.loss_repository.list_by_farm(
                farm.id,
                product_id=product_id,
                reason=reason,
                from_date=from_date,
                to_date=to_date,
            )
            return [self._to_response(loss) for loss in losses]

    @staticmethod
    def _to_response(loss) -> EggLossResponse:
        return EggLossResponse(
            id=loss.id,
            farm_id=loss.farm_id,
            product_id=loss.product_id,
            quantity=loss.quantity,
            unit_id=loss.unit_id,
            conversion_factor=loss.conversion_factor,
            quantity_in_base_unit=(
                loss.quantity * loss.conversion_factor
            ).quantize(Decimal("0.001")),
            loss_date=loss.loss_date,
            reason=loss.reason,
            notes=loss.notes,
            created_at=loss.created_at,
            updated_at=loss.updated_at,
        )
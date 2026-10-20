from collections import defaultdict
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
from app.repositories.chicken_loss_repository import ChickenLossRepository
from app.repositories.chicken_transaction_item_repository import (
    ChickenTransactionItemRepository,
)
from app.schemas.chicken_loss import (
    ChickenLossCreateRequest,
    ChickenLossResponse,
)
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    InventoryMovementType,
)
from app.services.activity_service import ActivityService
from app.services.inventory_service import InventoryService

logger = get_application_logger()


class ChickenLossService:
    def __init__(
        self,
        loss_repository: ChickenLossRepository,
        chicken_batch_repository: ChickenBatchRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        block_repository: BlockRepository | None = None,
        chicken_transaction_item_repository: ChickenTransactionItemRepository | None = None,
        inventory_service: InventoryService | None = None,
    ) -> None:
        self.loss_repository = loss_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.block_repository = block_repository
        self.chicken_transaction_item_repository = chicken_transaction_item_repository
        self.inventory_service = inventory_service

    async def create_losses(
        self,
        farm: Farm,
        request: ChickenLossCreateRequest,
    ) -> list[ChickenLossResponse]:
        async with self.unit_of_work:
            batch_ids = {item.batch_id for item in request.items}
            batches = {}
            for batch_id in sorted(batch_ids, key=str):
                batch = await self.chicken_batch_repository.get_by_id(
                    farm.id,
                    batch_id,
                )
                if batch is None:
                    raise ResourceNotFoundError(
                        f"Chicken batch '{batch_id}' was not found for this farm."
                    )
                if batch.status != ChickenBatchStatus.ACTIVE:
                    raise ConflictError(
                        f"Cannot record loss from inactive batch '{batch.name}'."
                    )
                batches[batch_id] = batch

            blocks = {}
            if self.block_repository is not None:
                for block_id in sorted(
                    {item.block_id for item in request.items},
                    key=str,
                ):
                    block = await self.block_repository.get_by_id(farm.id, block_id)
                    if block is None:
                        raise ResourceNotFoundError(
                            "A loss block was not found for this farm."
                        )
                    blocks[block_id] = block

            requested_by_pair: defaultdict[tuple[UUID, UUID], int] = defaultdict(int)
            for item in request.items:
                requested_by_pair[(item.batch_id, item.block_id)] += item.quantity

            inventory_rows = {}
            for batch_id, block_id in sorted(
                requested_by_pair,
                key=lambda pair: (str(pair[0]), str(pair[1])),
            ):
                row = await self.batch_block_repository.get_by_batch_and_block(
                    batch_id,
                    block_id,
                )
                available = row.quantity if row is not None else 0
                requested = requested_by_pair[(batch_id, block_id)]
                if row is None or available < requested:
                    batch_name = batches[batch_id].name
                    raise ConflictError(
                        f"Cannot record loss of {requested} chickens from batch "
                        f"'{batch_name}' in block '{block_id}'; only {available} "
                        "are currently assigned there."
                    )
                inventory_rows[(batch_id, block_id)] = row

            for key, quantity in requested_by_pair.items():
                row = inventory_rows[key]
                row.quantity -= quantity
                await self.batch_block_repository.update(row)

            records = [
                {
                    "batch_id": item.batch_id,
                    "block_id": item.block_id,
                    "quantity": item.quantity,
                    "loss_date": request.loss_date,
                    "reason": item.reason,
                    "notes": item.notes,
                }
                for item in request.items
            ]
            losses = await self.loss_repository.create_many(farm.id, records)
            if (
                self.inventory_service is not None
                and self.chicken_transaction_item_repository is not None
            ):
                product_by_batch = {}
                for batch_id in batch_ids:
                    source_items = (
                        await self.chicken_transaction_item_repository.list_by_batch(
                            batch_id
                        )
                    )
                    product_ids = {
                        item.transaction_item.product_id for item in source_items
                    }
                    if not product_ids and getattr(
                        batches[batch_id], "is_opening_stock", False
                    ):
                        continue
                    if len(product_ids) != 1:
                        raise ConflictError(
                            "This chicken batch is not linked to exactly one chicken product; "
                            "the loss cannot be reflected in the product stock ledger."
                        )
                    product_by_batch[batch_id] = next(iter(product_ids))
                for loss in losses:
                    product_id = product_by_batch.get(loss.batch_id)
                    if product_id is None:
                        continue
                    await self.inventory_service.append_movement(
                        farm_id=farm.id,
                        user_id=farm.owner_id,
                        product_id=product_id,
                        quantity_delta=-Decimal(loss.quantity),
                        movement_type=InventoryMovementType.LOSS,
                        occurred_on=loss.loss_date,
                        notes=loss.notes or f"Chicken loss: {loss.reason.value}",
                        source_type="chicken_loss",
                        source_id=loss.id,
                        source_item_id=loss.id,
                    )

            total_quantity = sum(loss.quantity for loss in losses)
            loss_counts_by_reason: defaultdict[str, int] = defaultdict(int)
            for loss in losses:
                loss_counts_by_reason[loss.reason.value] += loss.quantity

            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.CHICKEN_LOSS_RECORDED,
                entity_type=ActivityEntityType.CHICKEN_LOSS,
                entity_id=losses[0].id,
                details={
                    "loss_ids": [str(loss.id) for loss in losses],
                    "loss_date": request.loss_date.isoformat(),
                    "item_count": len(losses),
                    "total_quantity": total_quantity,
                    "quantities_by_reason": dict(loss_counts_by_reason),
                    "items": [
                        {
                            "batch_name": batches[item.batch_id].name,
                            "block_id": str(item.block_id),
                            "block_name": (
                                blocks[item.block_id].name
                                if item.block_id in blocks
                                else None
                            ),
                            "quantity": loss.quantity,
                            "reason": loss.reason.value,
                            "notes": loss.notes,
                        }
                        for item, loss in zip(request.items, losses, strict=True)
                    ],
                },
            )
            await self.unit_of_work.commit()

            logger.info(
                "chicken_losses_recorded",
                extra={
                    "event": "chicken_losses_recorded",
                    "farm_id": farm.id,
                    "user_id": farm.owner_id,
                    "loss_ids": [loss.id for loss in losses],
                    "item_count": len(losses),
                    "total_quantity": total_quantity,
                },
            )
            return [
                ChickenLossResponse.model_validate(loss, from_attributes=True)
                for loss in losses
            ]

    async def list_losses(
        self,
        farm: Farm,
        *,
        batch_id: UUID | None = None,
        block_id: UUID | None = None,
        reason: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ChickenLossResponse]:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ConflictError("from_date must be on or before to_date.")
        async with self.unit_of_work:
            losses = await self.loss_repository.list_by_farm(
                farm.id,
                batch_id=batch_id,
                block_id=block_id,
                reason=reason,
                from_date=from_date,
                to_date=to_date,
            )
            return [
                ChickenLossResponse.model_validate(loss, from_attributes=True)
                for loss in losses
            ]
from datetime import date
from uuid import UUID

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.chicken_movement_repository import ChickenMovementRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.schemas.chicken_movement import (
    ChickenMovementBatchCreateRequest,
    ChickenMovementCreateRequest,
    ChickenMovementHistoryItem,
    ChickenMovementHistoryResponse,
    ChickenMovementResponse,
    MovementDirection,
)
from app.schemas.enums import (
    ActivityEntityType,
    ActivityType,
    ChickenBatchStatus,
    NotificationEventType,
)
from app.services.activity_service import ActivityService

logger = get_application_logger()


class ChickenMovementService:
    def __init__(
        self,
        movement_repository: ChickenMovementRepository,
        chicken_batch_repository: ChickenBatchRepository,
        block_repository: BlockRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
        activity_service: ActivityService,
        notification_outbox_repository: NotificationOutboxRepository | None = None,
    ) -> None:
        self.movement_repository = movement_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.block_repository = block_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work
        self.activity_service = activity_service
        self.notification_outbox_repository = notification_outbox_repository

    async def create_movement(
        self,
        farm: Farm,
        request: ChickenMovementCreateRequest,
    ) -> ChickenMovementResponse:
        if request.from_block_id == request.to_block_id:
            raise ConflictError("Chickens must be moved to a different block.")

        async with self.unit_of_work:
            batch = await self.chicken_batch_repository.get_by_id(
                farm.id,
                request.batch_id,
            )
            if batch is None:
                raise ResourceNotFoundError("Chicken batch not found for this farm.")
            if batch.status != ChickenBatchStatus.ACTIVE:
                raise ConflictError("Chickens can only be moved from an active batch.")

            locked_blocks = {}
            for block_id in sorted(
                {request.from_block_id, request.to_block_id},
                key=str,
            ):
                block = await self.block_repository.get_by_id_for_update(
                    farm.id,
                    block_id,
                )
                if block is None:
                    raise ResourceNotFoundError("Movement block not found for this farm.")
                if not block.is_active:
                    raise ConflictError("Chickens cannot be moved into or out of an inactive block.")
                locked_blocks[block_id] = block

            source = await self.batch_block_repository.get_by_batch_and_block(
                request.batch_id,
                request.from_block_id,
            )
            if source is None or source.quantity < request.quantity:
                available = source.quantity if source is not None else 0
                raise ConflictError(
                    f"Cannot move {request.quantity} chickens; only {available} "
                    "are assigned to the selected batch in the source block."
                )

            destination_block = locked_blocks[request.to_block_id]
            destination_total = (
                await self.batch_block_repository.get_total_quantity_by_block(
                    request.to_block_id
                )
            )
            capacity_limit = (
                destination_block.capacity + destination_block.over_capacity_limit
            )
            if destination_total + request.quantity > capacity_limit:
                available_capacity = max(capacity_limit - destination_total, 0)
                raise ConflictError(
                    f"Cannot move {request.quantity} chickens into block "
                    f"'{destination_block.name}'; only {available_capacity} spaces "
                    "remain including the over-capacity allowance."
                )

            destination = await self.batch_block_repository.get_by_batch_and_block(
                request.batch_id,
                request.to_block_id,
            )
            source.quantity -= request.quantity
            await self.batch_block_repository.update(source)
            if destination is None:
                await self.batch_block_repository.create(
                    {
                        "batch_id": request.batch_id,
                        "block_id": request.to_block_id,
                        "quantity": request.quantity,
                    }
                )
            else:
                destination.quantity += request.quantity
                await self.batch_block_repository.update(destination)

            movement = await self.movement_repository.create(
                farm.id,
                request.model_dump(),
            )
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.CHICKEN_MOVEMENT_CREATED,
                entity_type=ActivityEntityType.CHICKEN_MOVEMENT,
                entity_id=movement.id,
                details={
                    "batch_id": str(movement.batch_id),
                    "batch_name": batch.name,
                    "from_block_id": str(movement.from_block_id),
                    "from_block_name": locked_blocks[movement.from_block_id].name,
                    "to_block_id": str(movement.to_block_id),
                    "to_block_name": locked_blocks[movement.to_block_id].name,
                    "quantity": movement.quantity,
                    "movement_date": movement.movement_date.isoformat(),
                    "reason": movement.reason,
                    "notes": movement.notes,
                },
            )
            if self.notification_outbox_repository is not None:
                await self.notification_outbox_repository.enqueue(
                    farm_id=farm.id,
                    event_type=NotificationEventType.CHICKEN_MOVEMENT_RECORDED.value,
                    payload={"movement_id": str(movement.id)},
                    dedupe_key=f"chicken-movement.recorded:{movement.id}",
                )
            await self.unit_of_work.commit()
            logger.info(
                "chicken_movement_created",
                extra={
                    "event": "chicken_movement_created",
                    "farm_id": farm.id,
                    "user_id": farm.owner_id,
                    "movement_id": movement.id,
                    "batch_id": movement.batch_id,
                    "from_block_id": movement.from_block_id,
                    "to_block_id": movement.to_block_id,
                    "quantity": movement.quantity,
                },
            )
            return ChickenMovementResponse.model_validate(movement, from_attributes=True)

    async def create_batch_movement(
        self,
        farm: Farm,
        request: ChickenMovementBatchCreateRequest,
    ) -> list[ChickenMovementResponse]:
        if request.from_block_id == request.to_block_id:
            raise ConflictError("Choose two different blocks for the move.")

        async with self.unit_of_work:
            batches = {}
            for item in request.items:
                batch = await self.chicken_batch_repository.get_by_id(
                    farm.id,
                    item.batch_id,
                )
                if batch is None:
                    raise ResourceNotFoundError(
                        "One of the selected chicken batches is no longer available."
                    )
                if batch.status != ChickenBatchStatus.ACTIVE:
                    raise ConflictError(
                        f"'{batch.name}' is no longer an active batch. Refresh the list and choose an active batch."
                    )
                batches[item.batch_id] = batch

            locked_blocks = {}
            for block_id in sorted(
                {request.from_block_id, request.to_block_id},
                key=str,
            ):
                block = await self.block_repository.get_by_id_for_update(
                    farm.id,
                    block_id,
                )
                block_role = (
                    "source"
                    if block_id == request.from_block_id
                    else "destination"
                )
                if block is None:
                    raise ResourceNotFoundError(
                        f"The {block_role} block is no longer available."
                    )
                if not block.is_active:
                    raise ConflictError(
                        f"The {block_role} block '{block.name}' is no longer active. "
                        "Choose an active block."
                    )
                locked_blocks[block_id] = block

            source_rows = {}
            total_to_move = 0
            for item in request.items:
                source = await self.batch_block_repository.get_by_batch_and_block(
                    item.batch_id,
                    request.from_block_id,
                )
                available = source.quantity if source is not None else 0
                if available < item.quantity:
                    raise ConflictError(
                        f"'{batches[item.batch_id].name}' has only {available} chickens left in "
                        f"'{locked_blocks[request.from_block_id].name}'. Update its quantity or refresh the inventory."
                    )
                source_rows[item.batch_id] = source
                total_to_move += item.quantity

            destination_block = locked_blocks[request.to_block_id]
            destination_total = (
                await self.batch_block_repository.get_total_quantity_by_block(
                    request.to_block_id
                )
            )
            capacity_limit = (
                destination_block.capacity + destination_block.over_capacity_limit
            )
            available_capacity = max(capacity_limit - destination_total, 0)
            if total_to_move > available_capacity:
                raise ConflictError(
                    f"'{destination_block.name}' has room for {available_capacity} chickens, "
                    f"but {total_to_move} were selected. Reduce the quantities or choose another block."
                )

            destination_rows = {}
            for item in request.items:
                destination_rows[item.batch_id] = (
                    await self.batch_block_repository.get_by_batch_and_block(
                        item.batch_id,
                        request.to_block_id,
                    )
                )

            movements = []
            for item in request.items:
                source = source_rows[item.batch_id]
                source.quantity -= item.quantity
                await self.batch_block_repository.update(source)

                destination = destination_rows[item.batch_id]
                if destination is None:
                    await self.batch_block_repository.create(
                        {
                            "batch_id": item.batch_id,
                            "block_id": request.to_block_id,
                            "quantity": item.quantity,
                        }
                    )
                else:
                    destination.quantity += item.quantity
                    await self.batch_block_repository.update(destination)

                movement = await self.movement_repository.create(
                    farm.id,
                    {
                        "batch_id": item.batch_id,
                        "from_block_id": request.from_block_id,
                        "to_block_id": request.to_block_id,
                        "quantity": item.quantity,
                        "movement_date": request.movement_date,
                        "reason": request.reason,
                        "notes": request.notes,
                    },
                )
                movements.append(movement)

            for movement in movements:
                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    activity_type=ActivityType.CHICKEN_MOVEMENT_CREATED,
                    entity_type=ActivityEntityType.CHICKEN_MOVEMENT,
                    entity_id=movement.id,
                    details={
                        "batch_id": str(movement.batch_id),
                        "batch_name": batches[movement.batch_id].name,
                        "from_block_id": str(movement.from_block_id),
                        "from_block_name": locked_blocks[movement.from_block_id].name,
                        "to_block_id": str(movement.to_block_id),
                        "to_block_name": locked_blocks[movement.to_block_id].name,
                        "quantity": movement.quantity,
                        "movement_date": movement.movement_date.isoformat(),
                        "reason": movement.reason,
                        "notes": movement.notes,
                    },
                )
                if self.notification_outbox_repository is not None:
                    await self.notification_outbox_repository.enqueue(
                        farm_id=farm.id,
                        event_type=NotificationEventType.CHICKEN_MOVEMENT_RECORDED.value,
                        payload={"movement_id": str(movement.id)},
                        dedupe_key=f"chicken-movement.recorded:{movement.id}",
                    )

            await self.unit_of_work.commit()
            logger.info(
                "chicken_batch_movement_created",
                extra={
                    "event": "chicken_batch_movement_created",
                    "farm_id": farm.id,
                    "user_id": farm.owner_id,
                    "movement_ids": [movement.id for movement in movements],
                    "batch_count": len(movements),
                    "quantity": total_to_move,
                    "from_block_id": request.from_block_id,
                    "to_block_id": request.to_block_id,
                },
            )
            return [
                ChickenMovementResponse.model_validate(
                    movement,
                    from_attributes=True,
                )
                for movement in movements
            ]

    async def list_movements(
        self,
        farm: Farm,
        *,
        batch_id: UUID | None = None,
        from_block_id: UUID | None = None,
        to_block_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ChickenMovementResponse]:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ConflictError("from_date must be on or before to_date.")
        async with self.unit_of_work:
            movements = await self.movement_repository.list_by_farm(
                farm.id,
                batch_id=batch_id,
                from_block_id=from_block_id,
                to_block_id=to_block_id,
                from_date=from_date,
                to_date=to_date,
            )
            return [
                ChickenMovementResponse.model_validate(movement, from_attributes=True)
                for movement in movements
            ]

    async def list_block_history(
        self,
        farm: Farm,
        block_id: UUID,
        *,
        direction: MovementDirection = "all",
        search: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> ChickenMovementHistoryResponse:
        if from_date is not None and to_date is not None and from_date > to_date:
            raise ConflictError("from_date must be on or before to_date.")
        async with self.unit_of_work:
            rows, total_count = await self.movement_repository.list_block_history(
                farm.id,
                block_id,
                direction=direction,
                search=search.strip() if search else None,
                from_date=from_date,
                to_date=to_date,
                offset=offset,
                limit=limit,
            )
            return ChickenMovementHistoryResponse(
                items=[
                    ChickenMovementHistoryItem(
                        id=movement.id,
                        batch_id=movement.batch_id,
                        batch_name=batch_name,
                        from_block_id=movement.from_block_id,
                        from_block_name=from_block_name,
                        to_block_id=movement.to_block_id,
                        to_block_name=to_block_name,
                        quantity=movement.quantity,
                        movement_date=movement.movement_date,
                        reason=movement.reason,
                        notes=movement.notes,
                    )
                    for movement, batch_name, from_block_name, to_block_name in rows
                ],
                total_count=total_count,
                limit=limit,
                offset=offset,
            )
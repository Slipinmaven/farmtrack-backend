from datetime import date
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.blocks import Block
from app.models.farm import Farm
from app.repositories.block_repository import BlockRepository
from app.schemas.enums import ActivityEntityType, ActivityType
from app.schemas.block import (
    BlockBatchOccupancyResponse,
    BlockCreateRequest,
    BlockDetailResponse,
    BlockResponse,
    BlockUpdateRequest,
)
from app.services.activity_service import ActivityService
from app.services.activity_details import activity_field_changes

app_logger = get_application_logger()


def _is_block_name_conflict(error: IntegrityError) -> bool:
    original_error = error.orig
    while original_error is not None:
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "diag", None),
                "constraint_name",
                None,
            )
        if constraint_name == "uq_blocks_farm_id_name":
            return True
        original_error = original_error.__cause__ or original_error.__context__
    return False


class BlockService:
    def __init__(
        self,
        block_repository: BlockRepository,
        activity_service: ActivityService,
        unit_of_work: UnitOfWork,
    ):
        self.block_repository = block_repository
        self.activity_service = activity_service
        self.unit_of_work = unit_of_work

    async def list_blocks(
        self,
        farm: Farm,
        search: str | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[BlockResponse]:
        async with self.unit_of_work:
            blocks = await self.block_repository.list_by_farm(
                farm.id,
                search=search,
                is_active=is_active,
                limit=limit,
                offset=offset,
            )
            occupancy = await self.block_repository.get_occupancy_by_farm(farm.id)
            app_logger.info(
                "blocks_listed",
                extra={"event": "blocks_listed", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return [self._to_response(block, occupancy.get(block.id, 0)) for block in blocks]

    async def get_block(
        self,
        farm: Farm,
        block_id: UUID,
    ) -> BlockDetailResponse:
        async with self.unit_of_work:
            block = await self._get_block_or_raise(farm.id, block_id)
            occupied = await self.block_repository.get_occupied_chickens(
                farm.id,
                block.id,
            )
            batch_assignments = await self.block_repository.list_batch_occupancy(
                farm.id,
                block.id,
            )
            today = date.today()
            response = BlockDetailResponse(
                **self._to_response(block, occupied).model_dump(),
                batches=[
                    BlockBatchOccupancyResponse(
                        batch_id=assignment.batch.id,
                        batch_name=assignment.batch.name,
                        chicken_type=assignment.batch.chicken_type,
                        breed=assignment.batch.breed,
                        status=assignment.batch.status,
                        hatch_date=assignment.batch.hatch_date,
                        age_days=(
                            max((today - assignment.batch.hatch_date).days, 0)
                            if assignment.batch.hatch_date is not None
                            else None
                        ),
                        quantity=assignment.quantity,
                        notes=assignment.batch.notes,
                    )
                    for assignment in batch_assignments
                ],
            )
            app_logger.info(
                "block_retrieved",
                extra={
                    "event": "block_retrieved",
                    "user_id": farm.owner_id,
                    "farm_id": farm.id,
                },
            )
            return response

    async def create_block(
        self,
        farm: Farm,
        block_data: BlockCreateRequest,
    ) -> BlockResponse:
        try:
            async with self.unit_of_work:
                block = await self.block_repository.create(
                    farm.id,
                    block_data.model_dump(),
                )
                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    activity_type=ActivityType.BLOCK_CREATED,
                    entity_type=ActivityEntityType.BLOCK,
                    entity_id=block.id,
                    details={
                        "name": block.name,
                        "description": block.description,
                        "capacity": block.capacity,
                        "over_capacity_limit": block.over_capacity_limit,
                        "is_active": block.is_active,
                    },
                )
                await self.unit_of_work.commit()
                response = self._to_response(block, 0)
                app_logger.info(
                    "block_created",
                    extra={
                        "event": "block_created",
                        "user_id": farm.owner_id,
                        "farm_id": farm.id,
                    },
                )
                return response
        except IntegrityError as exc:
            if _is_block_name_conflict(exc):
                raise ConflictError(
                    "A block with this name already exists for this farm."
                ) from exc
            raise

    async def update_block(
        self,
        farm: Farm,
        block_id: UUID,
        block_data: BlockUpdateRequest,
    ) -> BlockResponse:
        try:
            async with self.unit_of_work:
                block = await self.block_repository.get_by_id_for_update(
                    farm.id,
                    block_id,
                )
                if block is None:
                    raise ResourceNotFoundError("Block not found.")
                update_data = block_data.model_dump(exclude_unset=True)
                occupied = await self.block_repository.get_occupied_chickens(
                    farm.id,
                    block.id,
                )
                next_capacity = update_data.get("capacity", block.capacity)
                next_over_capacity_limit = update_data.get(
                    "over_capacity_limit",
                    block.over_capacity_limit,
                )
                if occupied > next_capacity + next_over_capacity_limit:
                    raise ConflictError(
                        "The capacity limit cannot be lower than the current "
                        f"occupancy of {occupied} chickens."
                    )
                before_values = {
                    field: getattr(block, field) for field in update_data
                }
                for field, value in update_data.items():
                    setattr(block, field, value)
                block = await self.block_repository.update(block)
                changes = activity_field_changes(
                    before_values,
                    {field: getattr(block, field) for field in update_data},
                )
                if changes:
                    await self.activity_service.record(
                        farm_id=farm.id,
                        user_id=farm.owner_id,
                        activity_type=ActivityType.BLOCK_UPDATED,
                        entity_type=ActivityEntityType.BLOCK,
                        entity_id=block.id,
                        details={"name": block.name, "changes": changes},
                    )
                await self.unit_of_work.commit()
                response = self._to_response(block, occupied)
                app_logger.info(
                    "block_updated",
                    extra={
                        "event": "block_updated",
                        "user_id": farm.owner_id,
                        "farm_id": farm.id,
                    },
                )
                return response
        except IntegrityError as exc:
            if _is_block_name_conflict(exc):
                raise ConflictError(
                    "A block with this name already exists for this farm."
                ) from exc
            raise

    async def delete_block(
        self,
        farm: Farm,
        block_id: UUID,
    ) -> None:
        async with self.unit_of_work:
            block = await self.block_repository.get_by_id_for_update(
                farm.id,
                block_id,
            )
            if block is None:
                raise ResourceNotFoundError("Block not found.")
            occupied = await self.block_repository.get_occupied_chickens(
                farm.id,
                block.id,
            )
            if occupied:
                raise ConflictError(
                    f"Move or clear the {occupied} chickens assigned to this block "
                    "before deleting it."
                )
            await self.block_repository.delete(block)
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.BLOCK_DELETED,
                entity_type=ActivityEntityType.BLOCK,
                entity_id=block.id,
                details={
                    "name": block.name,
                    "description": block.description,
                    "capacity": block.capacity,
                    "over_capacity_limit": block.over_capacity_limit,
                    "is_active": block.is_active,
                },
            )
            await self.unit_of_work.commit()
            app_logger.info(
                "block_deleted",
                extra={"event": "block_deleted", "user_id": farm.owner_id, "farm_id": farm.id},
            )

    async def _get_block_or_raise(self, farm_id: UUID, block_id: UUID) -> Block:
        block = await self.block_repository.get_by_id(farm_id, block_id)
        if block is None:
            raise ResourceNotFoundError("Block not found.")
        return block

    @staticmethod
    def _to_response(block: Block, occupied_chickens: int) -> BlockResponse:
        return BlockResponse.model_validate(
            block,
            from_attributes=True,
        ).model_copy(update={"occupied_chickens": occupied_chickens})
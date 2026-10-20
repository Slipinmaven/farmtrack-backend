from uuid import UUID

from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.core.exceptions import ConflictError
from app.models.farm import Farm
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.chicken_sale import (
    ChickenSaleBatchOption,
    ChickenSaleBatchStock,
    ChickenSaleBlockOption,
    ChickenSaleOptionsResponse,
)
from app.schemas.enums import (
    ChickenBatchStatus,
    ProductType,
)
from app.schemas.product import ProductResponse, ProductUnitResponse
from app.schemas.transaction_settlement import (
    ChickenSettlementBatchOption,
    ChickenSettlementBlockOption,
    ChickenSettlementOptionsResponse,
)

app_logger = get_application_logger()


class ChickenSaleOptionsService:
    def __init__(
        self,
        product_repository: ProductRepository,
        block_repository: BlockRepository,
        chicken_batch_repository: ChickenBatchRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
    ):
        self.product_repository = product_repository
        self.block_repository = block_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work

    async def get_options(self, farm: Farm) -> ChickenSaleOptionsResponse:
        async with self.unit_of_work:
            products = await self.product_repository.list_by_farm(farm.id)
            blocks = await self.block_repository.list_by_farm(
                farm.id,
                is_active=True,
            )
            batches = await self.chicken_batch_repository.list_by_farm(
                farm.id,
                status=ChickenBatchStatus.ACTIVE,
            )
            estimated_unit_costs = (
                await self.chicken_batch_repository.get_estimated_purchase_unit_costs(
                    farm.id,
                    {batch.id for batch in batches},
                )
            )
            block_names = {block.id: block.name for block in blocks}
            stock_by_block = await self.batch_block_repository.get_total_quantities_by_blocks(
                {block.id for block in blocks}
            )

            response = ChickenSaleOptionsResponse(
                products=[
                    ProductResponse(
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
                    for product in products
                    if product.is_active
                    and product.is_sellable
                    and product.product_type == ProductType.CHICKENS
                ],
                blocks=[
                    ChickenSaleBlockOption(
                        id=block.id,
                        name=block.name,
                        capacity=block.capacity,
                        over_capacity_limit=block.over_capacity_limit,
                        maximum_chickens=(
                            block.capacity + block.over_capacity_limit
                        ),
                        current_chickens=stock_by_block.get(block.id, 0),
                        available_capacity=max(
                            0,
                            block.capacity
                            + block.over_capacity_limit
                            - stock_by_block.get(block.id, 0),
                        ),
                    )
                    for block in blocks
                ],
                batches=[
                    ChickenSaleBatchOption(
                        id=batch.id,
                        name=batch.name,
                        chicken_type=batch.chicken_type,
                        hatch_date=batch.hatch_date,
                        estimated_unit_cost=estimated_unit_costs.get(batch.id),
                        stocks=[
                            ChickenSaleBatchStock(
                                block_id=assignment.block_id,
                                block_name=block_names[assignment.block_id],
                                quantity=assignment.quantity,
                            )
                            for assignment in batch.batch_blocks
                            if assignment.quantity > 0
                            and assignment.block_id in block_names
                        ],
                    )
                    for batch in batches
                    if any(
                        assignment.quantity > 0
                        and assignment.block_id in block_names
                        for assignment in batch.batch_blocks
                    )
                ],
            )
            app_logger.info(
                "chicken_sale_options_loaded",
                extra={
                    "event": "chicken_sale_options_loaded",
                    "user_id": farm.owner_id,
                    "farm_id": farm.id,
                    "product_count": len(response.products),
                    "block_count": len(response.blocks),
                },
            )
            return response

    async def get_settlement_options(
        self,
        farm: Farm,
        *,
        selection: str,
        search: str | None,
        batch_id: UUID | None = None,
        block_id: UUID | None = None,
        offset: int = 0,
    ) -> ChickenSettlementOptionsResponse:
        async with self.unit_of_work:
            term = search.strip() if search and search.strip() else None
            if selection in {"receive_batch", "issue_batch"}:
                batches = await self.chicken_batch_repository.list_for_settlement(
                    farm.id,
                    search=term,
                    require_active_stock=selection == "issue_batch",
                    block_id=block_id,
                    limit=31,
                    offset=offset,
                )
                has_more = len(batches) > 30
                result_batches = []
                for batch, stock_total in batches[:30]:
                    result_batches.append(
                        ChickenSettlementBatchOption(
                            id=batch.id,
                            name=batch.name,
                            chicken_type=batch.chicken_type,
                            hatch_date=batch.hatch_date,
                            total_quantity=stock_total,
                        )
                    )
                return ChickenSettlementOptionsResponse(
                    batches=result_batches,
                    has_more=has_more,
                )

            if selection == "issue_block" and batch_id is None:
                block_stock_rows = await self.block_repository.list_active_with_chicken_stock(
                    farm.id,
                    search=term,
                    limit=31,
                    offset=offset,
                )
                has_more = len(block_stock_rows) > 30
                return ChickenSettlementOptionsResponse(
                    blocks=[
                        ChickenSettlementBlockOption(
                            id=block.id,
                            name=block.name,
                            current_chickens=quantity,
                            available_capacity=max(
                                0,
                                block.capacity
                                + block.over_capacity_limit
                                - quantity,
                            ),
                            batch_quantity=quantity,
                        )
                        for block, quantity in block_stock_rows[:30]
                    ],
                    has_more=has_more,
                )

            if selection == "issue_block":
                if batch_id is None:
                    raise ConflictError(
                        "Choose an active chicken batch before selecting its housing blocks."
                    )
                batch = await self.chicken_batch_repository.get_by_id(
                    farm.id,
                    batch_id,
                )
                if batch is None or batch.status != ChickenBatchStatus.ACTIVE:
                    raise ConflictError(
                        "Choose an active chicken batch before selecting its housing blocks."
                    )
                block_stock_rows = await self.block_repository.list_active_with_batch_stock(
                    farm.id,
                    batch_id,
                    search=term,
                    limit=31,
                    offset=offset,
                )
                blocks = [block for block, _ in block_stock_rows]
                stock_by_batch_block = {
                    block.id: quantity for block, quantity in block_stock_rows
                }
            else:
                blocks = await self.block_repository.list_by_farm(
                    farm.id,
                    search=term,
                    is_active=True,
                    limit=31,
                    offset=offset,
                )
                stock_by_batch_block = {}
            has_more = len(blocks) > 30
            blocks = blocks[:30]
            stock_by_block = await self.batch_block_repository.get_total_quantities_by_blocks(
                {block.id for block in blocks}
            )
            result_blocks = []
            for block in blocks:
                current_chickens = stock_by_block.get(block.id, 0)
                available_capacity = max(
                    0,
                    block.capacity
                    + block.over_capacity_limit
                    - current_chickens,
                )
                batch_quantity = (
                    stock_by_batch_block.get(block.id, 0)
                    if selection == "issue_block"
                    else None
                )
                if selection == "receive_block" and available_capacity <= 0:
                    continue
                if selection == "issue_block" and not batch_quantity:
                    continue
                result_blocks.append(
                    ChickenSettlementBlockOption(
                        id=block.id,
                        name=block.name,
                        current_chickens=current_chickens,
                        available_capacity=available_capacity,
                        batch_quantity=batch_quantity,
                    )
                )
            return ChickenSettlementOptionsResponse(
                blocks=result_blocks,
                has_more=has_more,
            )

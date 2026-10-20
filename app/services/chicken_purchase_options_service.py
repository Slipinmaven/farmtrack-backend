from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.repositories.batch_block_repository import BatchBlockRepository
from app.repositories.block_repository import BlockRepository
from app.repositories.chicken_batch_repository import ChickenBatchRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.chicken_purchase import (
    ChickenPurchaseBlockOption,
    ChickenPurchaseOptionsResponse,
)
from app.schemas.contact import ContactResponse
from app.schemas.enums import ChickenBatchStatus, ContactRoleEnum, ProductType
from app.schemas.product import ProductResponse, ProductUnitResponse

app_logger = get_application_logger()


class ChickenPurchaseOptionsService:
    def __init__(
        self,
        product_repository: ProductRepository,
        contact_repository: ContactRepository,
        block_repository: BlockRepository,
        chicken_batch_repository: ChickenBatchRepository,
        batch_block_repository: BatchBlockRepository,
        unit_of_work: UnitOfWork,
    ):
        self.product_repository = product_repository
        self.contact_repository = contact_repository
        self.block_repository = block_repository
        self.chicken_batch_repository = chicken_batch_repository
        self.batch_block_repository = batch_block_repository
        self.unit_of_work = unit_of_work

    async def get_options(self, farm: Farm) -> ChickenPurchaseOptionsResponse:
        async with self.unit_of_work:
            products = await self.product_repository.list_by_farm(farm.id)
            suppliers = await self.contact_repository.list_by_farm(farm.id)
            blocks = await self.block_repository.list_by_farm(
                farm.id,
                is_active=True,
            )
            batches = await self.chicken_batch_repository.list_by_farm(
                farm.id,
                status=ChickenBatchStatus.ACTIVE,
            )
            stock_by_block = await self.batch_block_repository.get_total_quantities_by_blocks(
                {block.id for block in blocks}
            )

            response = ChickenPurchaseOptionsResponse(
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
                    if product.is_active and product.product_type == ProductType.CHICKENS
                ],
                suppliers=[
                    ContactResponse(
                        id=contact.id,
                        farm_id=contact.farm_id,
                        name=contact.name,
                        roles=[role.role for role in contact.contact_roles],
                        phone=contact.phone,
                        email=contact.email,
                        address=contact.address,
                        notes=contact.notes,
                        created_at=contact.created_at,
                        updated_at=contact.updated_at,
                    )
                    for contact in suppliers
                    if any(
                        role.role == ContactRoleEnum.SUPPLIER
                        for role in contact.contact_roles
                    )
                ],
                blocks=[
                    ChickenPurchaseBlockOption(
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
                    {
                        "id": batch.id,
                        "name": batch.name,
                        "chicken_type": batch.chicken_type,
                        "hatch_date": batch.hatch_date,
                    }
                    for batch in batches
                ],
            )
            app_logger.info(
                "chicken_purchase_options_loaded",
                extra={
                    "event": "chicken_purchase_options_loaded",
                    "user_id": farm.owner_id,
                    "farm_id": farm.id,
                    "product_count": len(response.products),
                    "supplier_count": len(response.suppliers),
                    "block_count": len(response.blocks),
                    "batch_count": len(response.batches),
                },
            )
            return response

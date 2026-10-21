from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError
from app.schemas.chicken_sale import ChickenSaleRequest
from app.schemas.enums import ChickenType, ProductType
from app.services.chicken_sale_service import ChickenSaleService


class FakeUnitOfWork:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            self.rollbacks += 1

    async def commit(self):
        self.commits += 1


class FakeProductRepository:
    def __init__(self, product):
        self.product = product

    async def get_by_id(self, farm_id, product_id):
        return self.product if product_id == self.product.id else None


class FakeTransactionService:
    def __init__(self, ordered_quantity):
        self.ordered_quantity = ordered_quantity
        self.commit_argument = None
        self.transaction_data = None

    async def create_transaction(
        self,
        farm_id,
        transaction_data,
        user_id=None,
        *,
        commit=True,
    ):
        self.commit_argument = commit
        self.transaction_data = transaction_data
        return SimpleNamespace(
            id=uuid4(),
            transaction_date=transaction_data.transaction_date or date.today(),
            items=[
                SimpleNamespace(
                    id=uuid4(),
                    ordered_base_quantity=Decimal(self.ordered_quantity),
                )
            ],
        )


class FakeSaleDeliveryService:
    def __init__(self):
        self.request = None
        self.commit_argument = None

    async def create_delivery(
        self,
        farm_id,
        transaction_id,
        request,
        user_id=None,
        *,
        commit=True,
    ):
        self.request = request
        self.commit_argument = commit


def make_service(ordered_quantity=3):
    product = SimpleNamespace(
        id=uuid4(),
        is_active=True,
        is_sellable=True,
        product_type=ProductType.CHICKENS,
    )
    unit_of_work = FakeUnitOfWork()
    transactions = FakeTransactionService(ordered_quantity)
    deliveries = FakeSaleDeliveryService()
    service = ChickenSaleService(
        product_repository=FakeProductRepository(product),
        transaction_service=transactions,
        sale_delivery_service=deliveries,
        unit_of_work=unit_of_work,
    )
    return service, product, unit_of_work, transactions, deliveries


def make_request(product_id, quantity=3):
    return ChickenSaleRequest(
        customer_id=uuid4(),
        transaction_date=date.today(),
        transaction_time=time(14, 25),
        discount_type="percentage",
        discount_value="10.00",
        discount_reason="Loyal customer",
        items=[
            {
                "product_id": product_id,
                "chicken_type": ChickenType.LAYERS,
                "quantity": quantity,
                "unit_id": uuid4(),
                "unit_price": "250.00",
                "batch_allocations": [
                    {
                        "batch_id": uuid4(),
                        "block_id": uuid4(),
                        "quantity": quantity,
                    }
                ],
            }
        ],
    )


@pytest.mark.asyncio
async def test_chicken_sale_records_transaction_and_deducts_allocated_stock_atomically():
    service, product, unit_of_work, transactions, deliveries = make_service()

    await service.create_chicken_sale(
        uuid4(),
        make_request(product.id),
    )

    assert transactions.commit_argument is False
    assert transactions.transaction_data.discount_type == "percentage"
    assert transactions.transaction_data.discount_value == Decimal("10.00")
    assert transactions.transaction_data.discount_reason == "Loyal customer"
    assert transactions.transaction_data.transaction_time == time(14, 25)
    assert deliveries.commit_argument is False
    assert deliveries.request.delivered_time == time(14, 25)
    assert deliveries.request.items[0].quantity_delivered == 3
    assert deliveries.request.items[0].batch_allocations[0].quantity == 3
    assert unit_of_work.commits == 1


@pytest.mark.asyncio
async def test_chicken_sale_can_be_recorded_as_an_order_without_delivering_stock():
    service, product, unit_of_work, transactions, deliveries = make_service()
    payload = make_request(product.id).model_dump()
    payload["items"][0].pop("batch_allocations")
    request = ChickenSaleRequest.model_validate(payload)

    await service.create_chicken_sale(uuid4(), request)

    assert transactions.transaction_data.items[0].quantity == Decimal("3")
    assert transactions.transaction_data.items[0].batch_allocations == []
    assert deliveries.request is None
    assert unit_of_work.commits == 1


@pytest.mark.asyncio
async def test_chicken_sale_can_be_recorded_without_a_customer():
    service, product, _, transactions, _ = make_service()
    request = make_request(product.id).model_copy(update={"customer_id": None})

    await service.create_chicken_sale(uuid4(), request)

    assert transactions.transaction_data.contact_id is None


@pytest.mark.asyncio
async def test_chicken_sale_rejects_product_not_marked_sellable():
    service, product, unit_of_work, transactions, deliveries = make_service()
    product.is_sellable = False

    with pytest.raises(ConflictError, match="not marked as available for sale"):
        await service.create_chicken_sale(uuid4(), make_request(product.id))

    assert unit_of_work.commits == 0
    assert transactions.transaction_data is None
    assert deliveries.request is None


@pytest.mark.asyncio
async def test_chicken_sale_rolls_back_when_allocations_do_not_cover_item_quantity():
    service, product, unit_of_work, _, deliveries = make_service(ordered_quantity=4)

    with pytest.raises(ConflictError, match="allocation totals"):
        await service.create_chicken_sale(
            uuid4(),
            make_request(product.id, quantity=3),
        )

    assert deliveries.request is None
    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictError
from app.schemas.enums import ProductType
from app.services.farm_service import FarmService


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def commit(self):
        return None


class FakeRepository:
    def __init__(self, items):
        self.items = items
        self.updated = []

    async def list_by_farm(self, farm_id, **kwargs):
        if "is_active" in kwargs:
            return [
                item
                for item in self.items
                if item.is_active == kwargs["is_active"]
            ]
        return self.items

    async def update(self, item):
        self.updated.append(item)
        return item

    async def get_farm_settings(self, farm_id):
        return self.items[0] if self.items else None


class FakeActivityService:
    async def record(self, **kwargs):
        return None


def make_service(*, chicken_products, blocks):
    now = datetime.now(timezone.utc)
    farm = SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        name="Green Valley",
        description=None,
        location=None,
        phone_number=None,
        email=None,
        maximum_chicken_capacity=None,
        is_active=True,
        setup_completed_at=None,
        created_at=now,
        updated_at=now,
        farm_settings=None,
    )
    farm_repository = FakeRepository([])
    product_repository = FakeRepository(chicken_products)
    block_repository = FakeRepository(blocks)
    service = FarmService(
        farm_repository=farm_repository,
        farm_settings_repository=FakeRepository([]),
        activity_service=FakeActivityService(),
        unit_of_work=FakeUnitOfWork(),
        product_repository=product_repository,
        block_repository=block_repository,
    )
    return service, farm, farm_repository


@pytest.mark.asyncio
async def test_complete_setup_requires_an_active_chicken_product():
    service, farm, _ = make_service(
        chicken_products=[
            SimpleNamespace(is_active=False, product_type=ProductType.CHICKENS)
        ],
        blocks=[SimpleNamespace(is_active=True)],
    )

    with pytest.raises(ConflictError, match="active chicken product"):
        await service.complete_setup(farm)


@pytest.mark.asyncio
async def test_complete_setup_requires_an_active_block():
    service, farm, _ = make_service(
        chicken_products=[
            SimpleNamespace(is_active=True, product_type=ProductType.CHICKENS)
        ],
        blocks=[SimpleNamespace(is_active=False)],
    )

    with pytest.raises(ConflictError, match="active housing block"):
        await service.complete_setup(farm)


@pytest.mark.asyncio
async def test_complete_setup_persists_completion_after_required_setup():
    service, farm, farm_repository = make_service(
        chicken_products=[
            SimpleNamespace(is_active=True, product_type=ProductType.CHICKENS)
        ],
        blocks=[SimpleNamespace(is_active=True)],
    )

    response = await service.complete_setup(farm)

    assert farm.setup_completed_at is not None
    assert response.setup_completed_at == farm.setup_completed_at
    assert farm_repository.updated == [farm]


@pytest.mark.asyncio
async def test_complete_setup_returns_settings_without_lazy_loading_farm_relationship():
    service, farm, _ = make_service(
        chicken_products=[
            SimpleNamespace(is_active=True, product_type=ProductType.CHICKENS)
        ],
        blocks=[SimpleNamespace(is_active=True)],
    )
    now = datetime.now(timezone.utc)
    settings = SimpleNamespace(
        id=uuid4(),
        farm_id=farm.id,
        primary_color="#226B68",
        secondary_color="#BF6C52",
        font_family=None,
        font_scale=None,
        theme_mode="system",
        logo_path=None,
        currency="KES",
        timezone="Africa/Nairobi",
        created_at=now,
        updated_at=now,
    )
    service.farm_settings_repository.items = [settings]

    response = await service.complete_setup(farm)

    assert response.settings is not None
    assert response.settings.id == settings.id

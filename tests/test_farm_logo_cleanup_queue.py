from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.farm_logo_cleanup_job import FarmLogoCleanupJob
from app.schemas.farm import FarmSettingsUpdate
from app.services.farm_service import FarmService


class FakeSession:
    def __init__(self):
        self.added = []
        self.events = []

    def add(self, record):
        self.added.append(record)
        if isinstance(record, FarmLogoCleanupJob):
            self.events.append("cleanup_queued")


class FakeUnitOfWork:
    def __init__(self):
        self.session = FakeSession()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def commit(self):
        self.session.events.append("committed")


class FakeFarmSettingsRepository:
    def __init__(self, settings):
        self.settings = settings

    async def get_farm_settings(self, farm_id):
        return self.settings

    async def update_farm_settings(self, farm_id, settings_data):
        for field, value in settings_data.model_dump(exclude_unset=True).items():
            setattr(self.settings, field, value)
        return self.settings


class FakeActivityService:
    async def record(self, **kwargs):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("new_path", [None, "/media/farm-logos/farm/new.png"])
async def test_logo_change_queues_old_file_in_the_settings_transaction(new_path):
    farm_id = uuid4()
    old_path = f"/media/farm-logos/{farm_id}/old.png"
    now = datetime.now(timezone.utc)
    settings = SimpleNamespace(
        id=uuid4(),
        farm_id=farm_id,
        primary_color=None,
        secondary_color=None,
        font_family=None,
        font_scale=None,
        theme_mode="system",
        logo_path=old_path,
        currency=None,
        timezone=None,
        created_at=now,
        updated_at=now,
    )
    unit_of_work = FakeUnitOfWork()
    service = FarmService(
        farm_repository=None,
        farm_settings_repository=FakeFarmSettingsRepository(settings),
        activity_service=FakeActivityService(),
        unit_of_work=unit_of_work,
    )
    farm = SimpleNamespace(id=farm_id, owner_id=uuid4(), name="Test farm")

    response = await service.update_farm_settings(
        farm,
        FarmSettingsUpdate(logo_path=new_path),
    )

    cleanup_jobs = [
        record
        for record in unit_of_work.session.added
        if isinstance(record, FarmLogoCleanupJob)
    ]
    assert len(cleanup_jobs) == 1
    assert cleanup_jobs[0].logo_path == old_path
    assert unit_of_work.session.events[-2:] == ["cleanup_queued", "committed"]
    assert response.logo_path == (
        f"/api/v1/farms/{farm_id}/logo" if new_path is not None else None
    )

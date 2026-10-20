from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette import status

from app.api.v1.endpoints import farm as farm_endpoint
from app.core.exception_handlers import register_exception_handlers
from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_farm_service
from app.schemas.farm import FarmSettingsResponse
from app.services.farm_logo_storage import FarmLogoStorage


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class FakeFarmService:
    def __init__(self):
        self.logo_path = None
        self.farm_id = uuid4()

    async def get_farm_with_settings(self, farm):
        return SimpleNamespace(
            settings=SimpleNamespace(logo_path=self.logo_path)
            if self.logo_path
            else None
        )

    async def update_farm_settings(self, farm, settings_data):
        self.logo_path = settings_data.logo_path
        now = datetime.now(timezone.utc)
        return FarmSettingsResponse(
            id=uuid4(),
            farm_id=self.farm_id,
            primary_color=None,
            secondary_color=None,
            font_family=None,
            font_scale=None,
            theme_mode="system",
            logo_path=self.logo_path,
            currency=None,
            timezone=None,
            created_at=now,
            updated_at=now,
        )


def create_test_client(tmp_path, monkeypatch):
    service = FakeFarmService()
    farm = SimpleNamespace(id=service.farm_id, owner_id=uuid4(), name="Test farm")
    monkeypatch.setattr(farm_endpoint, "logo_storage", FarmLogoStorage(tmp_path))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(farm_endpoint.router)
    app.dependency_overrides[get_owned_farm] = lambda: farm
    app.dependency_overrides[get_farm_service] = lambda: service
    return TestClient(app), service, farm


def test_upload_and_delete_farm_logo(tmp_path, monkeypatch):
    client, service, farm = create_test_client(tmp_path, monkeypatch)

    response = client.post(
        f"/farms/{farm.id}/logo",
        files={"file": ("farm.png", PNG_HEADER + b"image bytes", "image/png")},
    )

    assert response.status_code == status.HTTP_200_OK
    logo_path = response.json()["logo_path"]
    logo_file = tmp_path / logo_path.removeprefix("/media/")
    assert logo_file.read_bytes() == PNG_HEADER + b"image bytes"
    assert service.logo_path == logo_path

    delete_response = client.delete(f"/farms/{farm.id}/logo")

    assert delete_response.status_code == status.HTTP_200_OK
    assert delete_response.json()["logo_path"] is None
    assert service.logo_path is None
    assert not logo_file.exists()


def test_upload_rejects_invalid_image_without_changing_logo(tmp_path, monkeypatch):
    client, service, farm = create_test_client(tmp_path, monkeypatch)
    service.logo_path = "/media/farm-logos/existing/logo.png"

    response = client.post(
        f"/farms/{farm.id}/logo",
        files={"file": ("farm.svg", b"<svg />", "image/svg+xml")},
    )

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert service.logo_path == "/media/farm-logos/existing/logo.png"

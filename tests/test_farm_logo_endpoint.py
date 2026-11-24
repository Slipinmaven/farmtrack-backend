from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette import status

from app.api.v1.endpoints import farm as farm_endpoint
from app.core.exception_handlers import register_exception_handlers
from app.dependencies.farm import get_farm_manager, get_owned_farm
from app.presentation.dependencies.services import get_farm_service
from app.schemas.farm import FarmSettingsResponse
from app.services.farm_logo_storage import FarmLogoStorage


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class FakeFarmService:
    def __init__(self):
        self.logo_path = None
        self.farm_id = uuid4()
        self.cleanup_paths = []

    async def get_farm_with_settings(self, farm):
        return SimpleNamespace(
            settings=SimpleNamespace(logo_path=self.logo_path)
            if self.logo_path
            else None
        )

    async def get_farm_logo_path(self, farm):
        return self.logo_path

    async def update_farm_settings(self, farm, settings_data):
        if self.logo_path and self.logo_path != settings_data.logo_path:
            self.cleanup_paths.append(self.logo_path)
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
    app.dependency_overrides[get_farm_manager] = lambda: farm
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
    assert logo_path == f"/api/v1/farms/{farm.id}/logo"
    assert service.logo_path.startswith(f"/media/farm-logos/{farm.id}/")
    logo_file = tmp_path / service.logo_path.removeprefix("/media/")
    assert logo_file.read_bytes() == PNG_HEADER + b"image bytes"
    stored_path = service.logo_path

    delete_response = client.delete(f"/farms/{farm.id}/logo")

    assert delete_response.status_code == status.HTTP_200_OK
    assert delete_response.json()["logo_path"] is None
    assert service.logo_path is None
    assert service.cleanup_paths == [stored_path]
    assert logo_file.exists()


def test_logo_download_requires_authorized_farm_access(tmp_path, monkeypatch):
    client, service, farm = create_test_client(tmp_path, monkeypatch)
    service.logo_path = FarmLogoStorage(tmp_path).save(
        farm.id,
        "image/png",
        PNG_HEADER + b"private image",
    )

    unauthorized = client.get(f"/farms/{farm.id}/logo")
    assert unauthorized.status_code == status.HTTP_401_UNAUTHORIZED

    client.app.dependency_overrides[get_owned_farm] = lambda: farm
    response = client.get(f"/farms/{farm.id}/logo")

    assert response.status_code == status.HTTP_200_OK
    assert response.content == PNG_HEADER + b"private image"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["vary"] == "Authorization"


def test_logo_download_hides_missing_and_cross_farm_files(tmp_path, monkeypatch):
    client, service, farm = create_test_client(tmp_path, monkeypatch)
    client.app.dependency_overrides[get_owned_farm] = lambda: farm
    other_farm_id = uuid4()
    service.logo_path = FarmLogoStorage(tmp_path).save(
        other_farm_id,
        "image/png",
        PNG_HEADER + b"other farm",
    )

    response = client.get(f"/farms/{farm.id}/logo")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_upload_rejects_invalid_image_without_changing_logo(tmp_path, monkeypatch):
    client, service, farm = create_test_client(tmp_path, monkeypatch)
    service.logo_path = "/media/farm-logos/existing/logo.png"

    response = client.post(
        f"/farms/{farm.id}/logo",
        files={"file": ("farm.svg", b"<svg />", "image/svg+xml")},
    )

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert service.logo_path == "/media/farm-logos/existing/logo.png"


def test_generic_settings_cannot_set_a_logo_path(tmp_path, monkeypatch):
    client, service, farm = create_test_client(tmp_path, monkeypatch)

    response = client.patch(
        f"/farms/{farm.id}/settings",
        json={"logo_path": "/media/farm-logos/other-farm/logo.png"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert service.logo_path is None

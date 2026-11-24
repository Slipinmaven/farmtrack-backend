from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.ai_assistant import router as assistant_router
from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import AuthorizationError
from app.dependencies.auth import get_current_user, require_super_admin
from app.dependencies.farm import get_owned_farm
from app.models.user import User
from app.presentation.dependencies.services import get_farm_assistant_service
from app.schemas.auth import UserResponse
from app.schemas.enums import UserRole


@pytest.mark.asyncio
async def test_super_admin_can_access_tool_enabled_assistant():
    admin = SimpleNamespace(role=UserRole.SUPER_ADMIN.value)

    assert await require_super_admin(admin) is admin


@pytest.mark.asyncio
async def test_scheduled_super_admin_cannot_access_tool_enabled_assistant():
    admin = SimpleNamespace(
        role=UserRole.SUPER_ADMIN.value,
        deletion_requested_at=datetime.now(UTC),
    )

    with pytest.raises(AuthorizationError, match="Farm access is paused"):
        await require_super_admin(admin)


@pytest.mark.asyncio
async def test_regular_user_cannot_access_tool_enabled_assistant():
    user = SimpleNamespace(role=UserRole.USER.value)

    with pytest.raises(AuthorizationError, match="currently in testing"):
        await require_super_admin(user)


def test_all_assistant_routes_are_server_side_role_gated():
    assert any(
        dependency.dependency is require_super_admin
        for dependency in assistant_router.dependencies
    )


def test_non_admin_is_denied_assistant_api_requests():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(assistant_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid4(),
        role=UserRole.USER.value,
    )
    app.dependency_overrides[get_owned_farm] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[get_farm_assistant_service] = lambda: pytest.fail(
        "The assistant service must not run for a regular user."
    )

    with TestClient(app) as client:
        response = client.get(
            f"/farms/{uuid4()}/assistant/conversations",
        )

    assert response.status_code == 403
    assert "currently in testing" in response.json()["error"]["message"]


def test_user_response_exposes_global_role():
    user = User(
        id=uuid4(),
        email="owner@example.com",
        password_hash="hash",
        role=UserRole.SUPER_ADMIN.value,
    )

    response = UserResponse.model_validate(user)

    assert response.role == UserRole.SUPER_ADMIN

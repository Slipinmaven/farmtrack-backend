from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.presentation.dependencies.services import get_security_settings_service
from app.models.user import User
from app.schemas.security_settings import (
    SecuritySettingsResponse,
    SecuritySettingsUpdate,
)
from app.services.security_settings_service import SecuritySettingsService


router = APIRouter(
    prefix="/security-settings",
    tags=["Security Settings"],
)


@router.get("", response_model=SecuritySettingsResponse)
async def get_security_settings(
    current_user: User = Depends(get_current_user),
    service: SecuritySettingsService = Depends(get_security_settings_service),
) -> SecuritySettingsResponse:
    return await service.get_for_user(current_user)


@router.patch("", response_model=SecuritySettingsResponse)
async def update_security_settings(
    request: SecuritySettingsUpdate,
    current_user: User = Depends(get_current_user),
    service: SecuritySettingsService = Depends(get_security_settings_service),
) -> SecuritySettingsResponse:
    return await service.update_for_user(current_user, request)
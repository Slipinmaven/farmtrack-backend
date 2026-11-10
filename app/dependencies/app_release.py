from fastapi import Depends

from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.dependencies.auth import get_current_user
from app.models.user import User


async def require_app_release_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    allowed_emails = set(settings.app_release_admin_emails)
    if not allowed_emails or current_user.email.strip().lower() not in allowed_emails:
        raise AuthorizationError(
            "You are not authorized to manage app releases."
        )
    return current_user

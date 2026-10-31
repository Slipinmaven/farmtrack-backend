from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from app.core.exceptions import AuthenticationError
from app.core.request_context import auth_session_id_context, auth_user_id_context
from app.core.security import decode_access_token
from app.dependencies.services import get_auth_service
from app.models.user import User
from app.services.auth_service import AuthService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    service: AuthService = Depends(get_auth_service),
) -> AsyncIterator[User]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authentication failed.")

    try:
        payload = decode_access_token(credentials.credentials)
        if (
            payload.get("type") != "access"
            or not payload.get("sub")
            or not payload.get("sid")
        ):
            raise AuthenticationError("Authentication failed.")
        user_id = UUID(str(payload["sub"]))
        session_id = UUID(str(payload["sid"]))
    except (PyJWTError, ValueError, TypeError):
        raise AuthenticationError("Authentication failed.") from None

    user = await service.get_active_user(user_id, session_id)
    request.state.auth_session_id = session_id
    context_token = auth_session_id_context.set(session_id)
    user_context_token = auth_user_id_context.set(user.id)
    try:
        yield user
    finally:
        auth_user_id_context.reset(user_context_token)
        auth_session_id_context.reset(context_token)

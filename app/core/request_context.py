from contextvars import ContextVar
from uuid import UUID


auth_session_id_context: ContextVar[UUID | None] = ContextVar(
    "auth_session_id",
    default=None,
)
auth_user_id_context: ContextVar[UUID | None] = ContextVar(
    "auth_user_id",
    default=None,
)
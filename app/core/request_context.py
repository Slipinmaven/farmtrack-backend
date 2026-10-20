from contextvars import ContextVar
from uuid import UUID


auth_session_id_context: ContextVar[UUID | None] = ContextVar(
    "auth_session_id",
    default=None,
)
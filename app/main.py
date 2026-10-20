import asyncio
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.database import async_session_factory, dispose_database_engine
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger, request_id_context
from app.services.notification_dispatcher import process_pending_notifications
from app.services.reminder_service import enqueue_due_reminder_notifications

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = get_logger("api")


async def _notification_worker_loop(interval_seconds: float = 5.0, batch_size: int = 20) -> None:
    while True:
        try:
            async with async_session_factory() as session:
                try:
                    await enqueue_due_reminder_notifications(session)
                    await process_pending_notifications(session, batch_size=batch_size)
                except Exception:
                    logger.exception(
                        "notification_worker_session_failed",
                        extra={"event": "notification_worker_session_failed"},
                    )
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "notification_worker_loop_failed",
                extra={"event": "notification_worker_loop_failed"},
            )
            await asyncio.sleep(interval_seconds)


def _request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "")
    return supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info("application_started", extra={"request_id": "-"})
    worker_task = asyncio.create_task(_notification_worker_loop())
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await dispose_database_engine()
        logger.info("application_stopped", extra={"request_id": "-"})


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)
register_exception_handlers(app)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = _request_id(request)
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        logger.exception(
            "unhandled_request_exception",
            extra={
                "event": "unhandled_request_exception",
                "method": request.method,
                "path": request.url.path,
                "request_id": request_id,
            },
        )
        raise
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "request_completed",
            extra={
                "event": "request_completed",
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "duration_ms": round(duration_ms, 2),
                "request_id": request_id,
            },
        )
        request_id_context.reset(token)


app.include_router(v1_router, prefix="/api/v1")
settings.media_directory.mkdir(parents=True, exist_ok=True)
app.mount(
    "/media",
    StaticFiles(directory=settings.media_directory),
    name="media",
)

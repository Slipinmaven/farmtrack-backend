from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, redact_sensitive_path, request_id_context

logger = get_logger("api")


def _error_response(
	code: str,
	message: str,
	request_id: str,
	status_code: int,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
	error: dict[str, object] = {
		"code": code,
		"message": message,
		"request_id": request_id,
	}
	if details is not None:
		error["details"] = details
	return JSONResponse(
		status_code=status_code,
		content={"error": error},
		headers={"X-Request-ID": request_id},
	)


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
	if not isinstance(exc, AppError):
		raise exc
	request_id = request_id_context.get()
	log = logger.error if exc.status_code >= 500 else logger.warning
	log(
		"application_error",
		extra={
			"event": "application_error",
			"path": redact_sensitive_path(request.url.path),
			"status": exc.status_code,
			"request_id": request_id,
			"error_code": exc.code,
		},
	)
	return _error_response(exc.code, exc.message, request_id, exc.status_code)


async def validation_error_handler(
	request: Request,
	exc: Exception,
) -> JSONResponse:
	if not isinstance(exc, RequestValidationError):
		raise exc
	request_id = request_id_context.get()
	return _error_response(
		"VALIDATION_ERROR",
		"Request validation failed.",
		request_id,
		422,
		details=[
			{
				"field": ".".join(str(part) for part in error.get("loc", ())),
				"message": error["msg"],
				"type": error["type"],
			}
			for error in exc.errors()
		],
	)


async def http_error_handler(
	request: Request,
	exc: Exception,
) -> JSONResponse:
	if not isinstance(exc, StarletteHTTPException):
		raise exc
	request_id = request_id_context.get()
	message = str(exc.detail) if isinstance(exc.detail, str) else "HTTP request failed."
	return _error_response("HTTP_ERROR", message, request_id, exc.status_code)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
	request_id = request_id_context.get()
	logger.exception(
		"unexpected_application_error",
		extra={
			"event": "unexpected_application_error",
			"path": redact_sensitive_path(request.url.path),
			"request_id": request_id,
		},
		exc_info=(type(exc), exc, exc.__traceback__),
	)
	message = "An unexpected error occurred."
	if settings.environment != "production" and settings.debug:
		message = "An unexpected error occurred. Check the server logs for details."
	return _error_response("INTERNAL_SERVER_ERROR", message, request_id, 500)


def register_exception_handlers(app: FastAPI) -> None:
	app.add_exception_handler(AppError, app_error_handler)
	app.add_exception_handler(RequestValidationError, validation_error_handler)
	app.add_exception_handler(StarletteHTTPException, http_error_handler)
	app.add_exception_handler(Exception, unexpected_error_handler)

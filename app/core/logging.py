import json
import logging
import logging.handlers
import re
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import settings

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
_DOWNLOAD_TOKEN_PATH = re.compile(r"(/api/v1/downloads/)[^/?#]+")


def redact_sensitive_path(path: str) -> str:
    return _DOWNLOAD_TOKEN_PATH.sub(r"\1[REDACTED]", path)


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "request_id": getattr(record, "request_id", request_id_context.get()),
            "message": record.getMessage().replace("\n", "\\n"),
        }

        for key in (
            "method",
            "path",
            "status",
            "duration_ms",
            "user_id",
            "farm_id",
            "error_code",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), default=str, ensure_ascii=True)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", request_id_context.get())
        return True


class AppLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("farmtrack.security") and record.levelno < logging.ERROR


class SecurityLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith("farmtrack.security")


class ErrorLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


class DateRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    def __init__(self, directory: Path, prefix: str, retention_days: int, level: int = logging.NOTSET):
        self.directory = directory
        self.prefix = prefix
        self.retention_days = retention_days
        self.directory.mkdir(parents=True, exist_ok=True)
        self._date_suffix = self._current_date()
        base_path = self.directory / f"{self.prefix}-{self._date_suffix}.log"
        super().__init__(base_path, when="midnight", interval=1, backupCount=0, encoding="utf-8")
        self.setLevel(level)
        self._prune_old_logs()

    @staticmethod
    def _current_date() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _target_path(self, target_date: str | None = None) -> Path:
        date_value = target_date or self._current_date()
        return self.directory / f"{self.prefix}-{date_value}.log"

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        current_date = self._current_date()
        if Path(self.baseFilename).name != f"{self.prefix}-{current_date}.log":
            return True
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        self.baseFilename = str(self._target_path(self._current_date()))
        self.stream = self._open()
        self._prune_old_logs()

    def _prune_old_logs(self) -> None:
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        for path in self.directory.glob(f"{self.prefix}-*.log"):
            try:
                date_part = path.stem.rsplit("-", 1)[-1]
                file_date = datetime.strptime(date_part, "%Y-%m-%d")
            except ValueError:
                continue
            if file_date < cutoff:
                path.unlink(missing_ok=True)


def configure_logging() -> None:
    root_dir = Path(settings.log_dir)
    app_dir = root_dir / "apps"
    error_dir = root_dir / "errors"
    security_dir = root_dir / "security"
    for directory in (root_dir, app_dir, error_dir, security_dir):
        directory.mkdir(parents=True, exist_ok=True)

    formatter = StructuredFormatter()
    request_filter = RequestIdFilter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(request_filter)

    app_handler = DateRotatingFileHandler(app_dir, "application", settings.log_retention_days)
    app_handler.setFormatter(formatter)
    app_handler.addFilter(request_filter)
    app_handler.addFilter(AppLogFilter())

    error_handler = DateRotatingFileHandler(error_dir, "error", settings.log_retention_days, level=logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.addFilter(request_filter)
    error_handler.addFilter(ErrorLogFilter())

    security_handler = DateRotatingFileHandler(
        security_dir,
        "security",
        settings.log_retention_days,
    )
    security_handler.setFormatter(formatter)
    security_handler.addFilter(request_filter)
    security_handler.addFilter(SecurityLogFilter())

    farmtrack_logger = logging.getLogger("farmtrack")
    farmtrack_logger.handlers.clear()
    farmtrack_logger.setLevel(getattr(logging, settings.log_level))
    farmtrack_logger.propagate = False
    for handler in (console_handler, app_handler, error_handler, security_handler):
        farmtrack_logger.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"farmtrack.{name}")


def get_application_logger() -> logging.Logger:
    return get_logger("application")


def get_error_logger() -> logging.Logger:
    return get_logger("error")


def get_security_logger() -> logging.Logger:
    return get_logger("security")

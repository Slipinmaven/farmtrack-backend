from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
from typing import Any


@dataclass
class AIProviderFailure(Exception):
    provider: str
    status_code: int
    reason: str
    cooldown_seconds: float
    retryable: bool
    provider_error_code: str | None = None
    provider_error_type: str | None = None
    provider_error_param: str | None = None


_DAILY_QUOTA_PATTERN = re.compile(
    r"per[\s_-]*day|daily|requests per day|quota.{0,30}day|day.{0,30}quota|"
    r"requestsperday|quotaid.{0,40}day",
    re.IGNORECASE,
)
_DURATION_PATTERN = re.compile(
    r"(?:(\d+(?:\.\d+)?)\s*h)?\s*"
    r"(?:(\d+(?:\.\d+)?)\s*m)?\s*"
    r"(?:(\d+(?:\.\d+)?)\s*s)?",
    re.I,
)


def provider_failure_from_response(
    provider: str,
    response: Any,
) -> AIProviderFailure:
    status_code = response.status_code
    body = _provider_error_text(response)
    retry_after = _retry_after_seconds(response)
    error_code, error_type, error_param = _provider_error_metadata(response)

    if status_code == 429:
        daily_quota = _DAILY_QUOTA_PATTERN.search(body) is not None
        cooldown = retry_after or (24 * 60 * 60 if daily_quota else 60)
        return AIProviderFailure(
            provider,
            status_code,
            "daily_quota" if daily_quota else "rate_limit",
            min(max(cooldown, 1), 24 * 60 * 60),
            True,
        )

    if status_code == 404:
        return AIProviderFailure(
            provider,
            status_code,
            "resource_not_found",
            5 * 60,
            True,
            error_code,
            error_type,
            error_param,
        )

    if error_code == "tool_use_failed":
        return AIProviderFailure(
            provider,
            status_code,
            "tool_use_failed",
            15,
            True,
            error_code,
            error_type,
            error_param,
        )

    retryable = status_code in {500, 502, 503}
    return AIProviderFailure(
        provider,
        status_code,
        "provider_failure" if retryable else "request_rejected",
        30 if retryable else 0,
        retryable,
        error_code,
        error_type,
        error_param,
    )


def provider_timeout_failure(provider: str) -> AIProviderFailure:
    return AIProviderFailure(provider, 0, "timeout", 15, True)


def _provider_error_text(response: Any) -> str:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return ""

    values: list[str] = []

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, child_key.casefold())
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif isinstance(value, str) and key in {
            "message",
            "status",
            "reason",
            "quotaid",
            "quotametric",
            "quota_id",
            "quota_metric",
        }:
            values.append(value)

    collect(payload)
    return " ".join(values)


def _provider_error_metadata(
    response: Any,
) -> tuple[str | None, str | None, str | None]:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return None, None, None

    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None, None, None

    def safe_value(key: str) -> str | None:
        value = error.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value) else None

    return safe_value("code"), safe_value("type"), safe_value("param")


def _retry_after_seconds(response: Any) -> float | None:
    raw = response.headers.get("retry-after")
    if raw:
        try:
            return max(float(raw), 1)
        except ValueError:
            try:
                reset_at = parsedate_to_datetime(raw)
                if reset_at.tzinfo is None:
                    reset_at = reset_at.replace(tzinfo=timezone.utc)
                return max(
                    (reset_at - datetime.now(timezone.utc)).total_seconds(),
                    1,
                )
            except (TypeError, ValueError, OverflowError):
                pass

    for header in ("x-ratelimit-reset-requests", "x-ratelimit-reset"):
        raw = response.headers.get(header)
        if not raw:
            continue
        try:
            return max(float(raw), 1)
        except ValueError:
            match = _DURATION_PATTERN.fullmatch(raw.strip())
            if match and any(match.groups()):
                hours, minutes, seconds = (
                    float(part or 0) for part in match.groups()
                )
                return max(hours * 3600 + minutes * 60 + seconds, 1)
    return None

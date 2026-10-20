from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import ConflictError
from app.schemas.enums import TransactionType


REFERENCE_PREFIXES = {
    TransactionType.SALE: "SAL",
    TransactionType.PURCHASE: "PUR",
}


def farm_local_date(
    timezone_name: str | None,
    now: datetime | None = None,
) -> date:
    configured_timezone = timezone_name or "UTC"
    try:
        timezone = ZoneInfo(configured_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConflictError("The farm timezone is invalid.") from exc

    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    return current_time.astimezone(timezone).date()


def format_transaction_reference(
    transaction_type: TransactionType,
    transaction_date: date,
    sequence_number: int,
) -> str:
    prefix = REFERENCE_PREFIXES[transaction_type]
    return f"{prefix}-{transaction_date:%Y%m%d}-{sequence_number:04d}"
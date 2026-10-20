from calendar import monthrange
from datetime import date, timedelta

from app.schemas.enums import AgeUnit


def _subtract_calendar_months(reference_date: date, months: int) -> date:
    month_index = reference_date.year * 12 + reference_date.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(reference_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def calculate_hatch_date(
    received_date: date,
    age: int | None,
    age_unit: AgeUnit | None,
) -> date | None:
    if age is None or age_unit is None:
        return None
    if age_unit == AgeUnit.DAYS:
        return received_date - timedelta(days=age)
    if age_unit == AgeUnit.WEEKS:
        return received_date - timedelta(weeks=age)
    if age_unit == AgeUnit.MONTHS:
        return _subtract_calendar_months(received_date, age)
    if age_unit == AgeUnit.YEARS:
        return _subtract_calendar_months(received_date, age * 12)
    raise ValueError(f"Unsupported age unit: {age_unit}")

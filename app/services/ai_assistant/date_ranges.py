import re
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.services.ai_assistant.contracts import DateRangeToolArguments, SalesReportToolArguments
from app.services.ai_assistant.prompts import current_farm_date, current_farm_datetime

_ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

_RELATIVE_DAY_COUNT_PATTERN = re.compile(
    r"\b(?:last|past|previous)\s+(\d{1,3})\s+days?\b"
)

_RELATIVE_HOUR_PATTERN = re.compile(
    r"\b(?:previous|last|past)\s+hour\b|\b(?:just\s+)?(?:an|one|1)\s+hour\s+ago\b"
)

_CLOCK_TIME_PATTERN = re.compile(
    r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)

def resolve_tool_date_range(
    arguments: DateRangeToolArguments,
    question: str,
    *,
    default_period: str,
    today: date | None = None,
) -> tuple[date | None, date | None]:
    local_today = today or current_farm_date()
    normalized_question = question.casefold()
    exact_dates = [
        date.fromisoformat(value)
        for value in _ISO_DATE_PATTERN.findall(question)
    ]
    if len(exact_dates) >= 2:
        start, end = exact_dates[0], exact_dates[1]
        return (end, start) if start > end else (start, end)
    if len(exact_dates) == 1:
        return exact_dates[0], exact_dates[0]

    if re.search(r"\byesterday\b", normalized_question):
        day = local_today - timedelta(days=1)
        return day, day
    if re.search(r"\btoday\b", normalized_question):
        return local_today, local_today

    if re.search(r"\blast week\b|\bprevious week\b", normalized_question):
        this_monday = local_today - timedelta(days=local_today.weekday())
        return this_monday - timedelta(days=7), this_monday - timedelta(days=1)
    if re.search(r"\bthis week\b|\bweek to date\b", normalized_question):
        return local_today - timedelta(days=local_today.weekday()), local_today

    if re.search(r"\blast month\b|\bprevious month\b", normalized_question):
        this_month_start = local_today.replace(day=1)
        last_month_end = this_month_start - timedelta(days=1)
        return last_month_end.replace(day=1), last_month_end
    if re.search(r"\bthis month\b|\bmonth to date\b", normalized_question):
        return local_today.replace(day=1), local_today

    if re.search(r"\blast year\b|\bprevious year\b", normalized_question):
        return date(local_today.year - 1, 1, 1), date(local_today.year - 1, 12, 31)
    if re.search(r"\bthis year\b|\byear to date\b", normalized_question):
        return date(local_today.year, 1, 1), local_today

    day_count = _RELATIVE_DAY_COUNT_PATTERN.search(normalized_question)
    if day_count:
        count = int(day_count.group(1))
        if 1 <= count <= 367:
            return local_today - timedelta(days=count - 1), local_today

    if arguments.from_date is not None and arguments.to_date is not None:
        return arguments.from_date, arguments.to_date
    if arguments.from_date is not None:
        return arguments.from_date, local_today
    if arguments.to_date is not None:
        return arguments.to_date, arguments.to_date

    if default_period == "month_to_date":
        return local_today.replace(day=1), local_today
    if default_period == "today":
        return local_today, local_today
    if default_period == "full_history":
        return None, None
    return local_today - timedelta(days=6), local_today

def resolve_sales_report_period(
    arguments: SalesReportToolArguments,
    question: str,
    *,
    now: datetime | None = None,
) -> tuple[date, date, time | None, time | None]:
    timezone = ZoneInfo(settings.timezone)
    local_now = now or current_farm_datetime()
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=timezone)
    else:
        local_now = local_now.astimezone(timezone)

    normalized_question = question.casefold()
    if _RELATIVE_HOUR_PATTERN.search(normalized_question):
        start = (
            local_now.astimezone(datetime_timezone.utc) - timedelta(hours=1)
        ).astimezone(timezone)
        return start.date(), local_now.date(), start.time(), local_now.time()

    date_range = resolve_tool_date_range(
        arguments,
        question,
        default_period="today",
        today=local_now.date(),
    )
    start_date, end_date = date_range
    if start_date is None or end_date is None:
        start_date = end_date = local_now.date()

    if arguments.from_time is not None and arguments.to_time is not None:
        return start_date, end_date, arguments.from_time, arguments.to_time

    clock_time = _CLOCK_TIME_PATTERN.search(question)
    if clock_time is None:
        if not re.search(
            r"\b(today|yesterday|last week|previous week|this week|"
            r"last month|previous month|this month|last year|previous year|"
            r"this year|year to date|month to date)\b|\b\d{4}-\d{2}-\d{2}\b",
            normalized_question,
        ) and arguments.from_date is None and arguments.to_date is None:
            start_date = end_date = local_now.date()
        return start_date, end_date, None, None

    hour = int(clock_time.group(1))
    minute = int(clock_time.group(2) or 0)
    suffix = clock_time.group(3).casefold().replace(".", "")
    if hour < 1 or hour > 12 or minute > 59:
        return start_date, end_date, None, None

    hour_24 = (hour % 12) + (12 if suffix == "pm" else 0)
    start = datetime.combine(
        start_date,
        time(hour_24, minute),
        tzinfo=timezone,
    )
    end = start + (timedelta(minutes=1) if clock_time.group(2) else timedelta(hours=1))
    return start.date(), end.date(), start.time(), end.time()

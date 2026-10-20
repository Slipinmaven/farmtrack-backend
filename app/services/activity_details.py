from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def activity_value(value: Any) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


def activity_field_changes(
    before: dict[str, object],
    after: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "field": field,
            "from": activity_value(old_value),
            "to": activity_value(new_value),
        }
        for field, old_value in before.items()
        if (new_value := after.get(field)) != old_value
    ]

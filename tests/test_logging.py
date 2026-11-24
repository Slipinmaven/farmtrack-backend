import json
import logging

from app.core.logging import StructuredFormatter


def test_structured_formatter_includes_provider_health_metadata():
    record = logging.LogRecord(
        name="farmtrack.ai_provider",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="provider marked unavailable",
        args=(),
        exc_info=None,
    )
    record.event = "ai_assistant_provider_health_changed"
    record.provider = "groq"
    record.status = 404
    record.reason = "resource_not_found"
    record.cooldown_seconds = 300

    payload = json.loads(StructuredFormatter().format(record))

    assert payload["provider"] == "groq"
    assert payload["status"] == 404
    assert payload["reason"] == "resource_not_found"
    assert payload["cooldown_seconds"] == 300

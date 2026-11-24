import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.exceptions import AppError
from app.services.ai_provider_errors import (
    AIProviderFailure,
    provider_failure_from_response,
)
from app.services.ai_provider_manager import (
    AIProviderManager,
    OpenAICompatibleProvider,
    get_ai_provider_manager,
)


class FakeProvider:
    def __init__(
        self,
        name: str,
        *,
        answer_result: str = "answer",
        chat_result: tuple[str, bool] = ("answer", False),
        failures: list[AIProviderFailure] | None = None,
    ) -> None:
        self.name = name
        self.answer_result = answer_result
        self.chat_result = chat_result
        self.failures = list(failures or [])
        self.answer_calls = 0
        self.chat_calls = 0

    def _fail_if_configured(self) -> None:
        if self.failures:
            raise self.failures.pop(0)

    async def answer(
        self,
        *,
        question: str,
        report_context: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        self.answer_calls += 1
        self._fail_if_configured()
        return self.answer_result

    async def answer_with_tools(
        self,
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: Any,
    ) -> tuple[str, bool]:
        self.chat_calls += 1
        self._fail_if_configured()
        return self.chat_result


def failure(
    provider: str,
    status_code: int,
    reason: str,
    *,
    cooldown: float = 30,
    retryable: bool = True,
) -> AIProviderFailure:
    return AIProviderFailure(provider, status_code, reason, cooldown, retryable)


@pytest.mark.asyncio
async def test_primary_429_fails_over_and_is_cooled_down_for_next_request():
    groq = FakeProvider(
        "groq",
        failures=[failure("groq", 429, "rate_limit", cooldown=45)],
    )
    gemini = FakeProvider("gemini", answer_result="Gemini answer")
    manager = AIProviderManager([groq, gemini])

    first = await manager.answer(question="Hello", report_context={})
    second = await manager.answer(question="Hello again", report_context={})

    assert first == "Gemini answer"
    assert second == "Gemini answer"
    assert groq.answer_calls == 1
    assert gemini.answer_calls == 2
    assert manager.health_snapshot()[0]["available"] is False
    assert manager.health_snapshot()[0]["last_failure_kind"] == "rate_limit"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400])
async def test_invalid_request_does_not_switch_provider(status_code: int):
    groq = FakeProvider(
        "groq",
        failures=[
            failure("groq", status_code, "request_rejected", retryable=False)
        ],
    )
    gemini = FakeProvider("gemini")
    manager = AIProviderManager([groq, gemini])

    with pytest.raises(AppError) as error:
        await manager.answer(question="Hello", report_context={})

    assert error.value.code == "AI_ASSISTANT_PROVIDER_REJECTED_REQUEST"
    assert error.value.status_code == 502
    assert groq.answer_calls == 1
    assert gemini.answer_calls == 0


@pytest.mark.asyncio
async def test_groq_tool_generation_failure_fails_over_without_changing_other_400s():
    groq = FakeProvider(
        "groq",
        failures=[
            failure(
                "groq",
                400,
                "tool_use_failed",
                cooldown=15,
                retryable=True,
            )
        ],
    )
    openrouter = FakeProvider(
        "openrouter",
        chat_result=("The inventory tool reports 12 bags.", False),
    )
    manager = AIProviderManager([groq, openrouter])

    async def execute_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return {"name": name, "arguments": arguments}

    answer, needs_clarification = await manager.answer_with_tools(
        question="How much feed do I have?",
        conversation_history=[],
        execute_tool=execute_tool,
    )

    assert (answer, needs_clarification) == (
        "The inventory tool reports 12 bags.",
        False,
    )
    assert groq.chat_calls == 1
    assert openrouter.chat_calls == 1
    assert manager.health_snapshot()[0]["last_failure_kind"] == "tool_use_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_auth_failure_does_not_switch_in_same_request_and_marks_provider_unhealthy(
    status_code: int,
):
    groq = FakeProvider(
        "groq",
        failures=[
            failure("groq", status_code, "request_rejected", retryable=False)
        ],
    )
    gemini = FakeProvider("gemini")
    manager = AIProviderManager([groq, gemini])

    with pytest.raises(AppError):
        await manager.answer(question="First", report_context={})

    assert gemini.answer_calls == 0
    assert manager.health_snapshot()[0]["available"] is False

    assert await manager.answer(question="Next", report_context={}) == "answer"
    assert groq.answer_calls == 1
    assert gemini.answer_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [0, 500, 502, 503])
async def test_provider_server_failures_switch_to_next_provider(status_code: int):
    failure_reason = "timeout" if status_code == 0 else "provider_failure"
    groq = FakeProvider(
        "groq",
        failures=[
            failure(
                "groq",
                status_code,
                failure_reason,
                cooldown=15 if status_code == 0 else 30,
            )
        ],
    )
    gemini = FakeProvider("gemini", answer_result="Recovered")
    manager = AIProviderManager([groq, gemini])

    assert await manager.answer(question="Hello", report_context={}) == "Recovered"
    assert groq.answer_calls == 1
    assert gemini.answer_calls == 1


@pytest.mark.asyncio
async def test_provider_not_found_fails_over_and_cools_down_provider():
    groq = FakeProvider(
        "groq",
        failures=[
            failure(
                "groq",
                404,
                "resource_not_found",
                cooldown=5 * 60,
            )
        ],
    )
    gemini = FakeProvider("gemini", answer_result="Recovered")
    manager = AIProviderManager([groq, gemini])

    assert await manager.answer(question="Hello", report_context={}) == "Recovered"

    health = manager.health_snapshot()[0]
    assert groq.answer_calls == 1
    assert gemini.answer_calls == 1
    assert health["available"] is False
    assert health["last_failure_kind"] == "resource_not_found"
    assert health["last_status_code"] == 404


@pytest.mark.asyncio
async def test_tool_result_is_cached_across_provider_failover():
    primary = FakeProvider(
        "groq",
        failures=[failure("groq", 503, "provider_failure")],
    )
    secondary = FakeProvider("gemini")
    manager = AIProviderManager([primary, secondary])
    tool_calls = 0

    async def execute_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal tool_calls
        tool_calls += 1
        return {"name": name, "arguments": arguments}

    async def primary_chat(
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: Any,
    ) -> tuple[str, bool]:
        await execute_tool("get_inventory_balances", {"product_name": "Feed"})
        raise failure("groq", 503, "provider_failure")

    async def secondary_chat(
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: Any,
    ) -> tuple[str, bool]:
        result = await execute_tool(
            "get_inventory_balances",
            {"product_name": "Feed"},
        )
        assert result["name"] == "get_inventory_balances"
        return "There is feed in stock.", False

    primary.answer_with_tools = primary_chat
    secondary.answer_with_tools = secondary_chat

    result = await manager.answer_with_tools(
        question="How much feed?",
        conversation_history=[],
        execute_tool=execute_tool,
    )

    assert result == ("There is feed in stock.", False)
    assert tool_calls == 1


def test_provider_failure_distinguishes_short_and_daily_quota():
    short_limit = httpx.Response(
        429,
        headers={"Retry-After": "8"},
        json={"error": {"message": "Too many requests"}},
    )
    daily_limit = httpx.Response(
        429,
        json={
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "quotaId": "GenerateRequestsPerDayPerProjectPerModel",
                    }
                ],
            }
        },
    )

    short_failure = provider_failure_from_response("groq", short_limit)
    daily_failure = provider_failure_from_response("gemini", daily_limit)

    assert short_failure.reason == "rate_limit"
    assert short_failure.cooldown_seconds == 8
    assert daily_failure.reason == "daily_quota"
    assert daily_failure.cooldown_seconds == 24 * 60 * 60


def test_provider_404_is_failover_eligible_with_cooldown():
    response = httpx.Response(
        404,
        json={
            "error": {
                "message": "Model not found",
                "code": "model_not_found",
                "type": "not_found_error",
            }
        },
    )

    provider_failure = provider_failure_from_response("groq", response)

    assert provider_failure.reason == "resource_not_found"
    assert provider_failure.retryable is True
    assert provider_failure.cooldown_seconds == 5 * 60
    assert provider_failure.provider_error_code == "model_not_found"
    assert provider_failure.provider_error_type == "not_found_error"


def test_provider_failure_logs_numeric_provider_error_codes():
    response = httpx.Response(
        404,
        json={"error": {"message": "No matching model", "code": 404}},
    )

    provider_failure = provider_failure_from_response("openrouter", response)

    assert provider_failure.provider_error_code == "404"


def test_provider_failure_extracts_safe_error_metadata_only():
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "Do not log prompt text: secret@example.com",
                "type": "invalid_request_error",
                "param": "temperature",
                "code": "unsupported_value",
            }
        },
    )

    provider_failure = provider_failure_from_response("groq", response)

    assert provider_failure.provider_error_type == "invalid_request_error"
    assert provider_failure.provider_error_param == "temperature"
    assert provider_failure.provider_error_code == "unsupported_value"
    assert "secret@example.com" not in repr(provider_failure)


def test_groq_tool_use_failed_is_retryable_but_other_400s_are_not():
    tool_failure = httpx.Response(
        400,
        json={
            "error": {
                "message": "Tool generation failed",
                "type": "invalid_request_error",
                "code": "tool_use_failed",
            }
        },
    )
    invalid_request = httpx.Response(
        400,
        json={
            "error": {
                "message": "Invalid parameter",
                "type": "invalid_request_error",
                "code": "invalid_request",
            }
        },
    )

    tool_error = provider_failure_from_response("groq", tool_failure)
    request_error = provider_failure_from_response("groq", invalid_request)

    assert tool_error.retryable is True
    assert tool_error.reason == "tool_use_failed"
    assert tool_error.provider_error_code == "tool_use_failed"
    assert request_error.retryable is False
    assert request_error.reason == "request_rejected"


@pytest.mark.asyncio
async def test_openai_compatible_provider_uses_shared_tool_schema(monkeypatch):
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": "tool-call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "get_contact_balances",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Nobody currently owes the farm.",
                        },
                    }
                ]
            },
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.services.ai_provider_manager.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    provider = OpenAICompatibleProvider(
        name="groq",
        api_key="test-key",
        model="test-model",
        base_url="https://api.groq.com/openai/v1",
    )
    tool_invocations: list[tuple[str, dict[str, Any]]] = []

    async def execute_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        tool_invocations.append((name, arguments))
        return {"accounts": []}

    answer, needs_clarification = await provider.answer_with_tools(
        question="Who owes me?",
        conversation_history=[],
        execute_tool=execute_tool,
    )

    assert answer == "Nobody currently owes the farm."
    assert not needs_clarification
    assert tool_invocations == [("get_contact_balances", {})]
    assert requests[0]["max_completion_tokens"] == 1024
    assert "max_tokens" not in requests[0]
    assert requests[0]["parallel_tool_calls"] is False
    definitions = requests[0]["tools"]
    assert all(item["type"] == "function" for item in definitions)
    assert all(
        item["function"]["parameters"]["type"] == "object"
        for item in definitions
    )
    assert requests[1]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "tool-call-1",
        "name": "get_contact_balances",
        "content": '{"accounts":[]}',
    }


def test_configured_provider_priority_is_groq_gemini_then_openrouter(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", SecretStr("groq-test"))
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("gemini-test"))
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("openrouter-test"))
    get_ai_provider_manager.cache_clear()

    try:
        manager = get_ai_provider_manager()
        assert [provider.name for provider in manager.providers] == [
            "groq",
            "gemini",
            "openrouter",
        ]
        openrouter = manager.providers[-1]
        assert isinstance(openrouter, OpenAICompatibleProvider)
        assert openrouter.model == settings.openrouter_model
        assert openrouter.model == "openrouter/free"
    finally:
        get_ai_provider_manager.cache_clear()

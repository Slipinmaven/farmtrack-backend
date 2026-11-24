import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import AppError
from app.services.ai_assistant_service import (
    CHAT_TOOLS,
    build_system_instruction,
    ClarificationToolArguments,
    PROFITABILITY_SYSTEM_INSTRUCTION,
    AssistantToolExecutor,
    GeminiClient,
)
from app.services.ai_provider_errors import (
    AIProviderFailure,
    provider_failure_from_response,
    provider_timeout_failure,
)

logger = logging.getLogger("farmtrack.ai_provider")


class AIProvider(Protocol):
    name: str

    async def answer(
        self,
        *,
        question: str,
        report_context: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str: ...

    async def answer_with_tools(
        self,
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: AssistantToolExecutor,
    ) -> tuple[str, bool]: ...


@dataclass
class ProviderHealth:
    cooldown_until: float = 0
    disabled: bool = False
    last_failure_kind: str | None = None
    last_status_code: int | None = None
    last_success_at: float | None = None


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        model: str,
        base_url: str,
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.model = model
        self.url = f"{base_url.rstrip('/')}/chat/completions"

    async def answer(
        self,
        *,
        question: str,
        report_context: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        messages = [
            {"role": "system", "content": PROFITABILITY_SYSTEM_INSTRUCTION},
            *self._history_messages(conversation_history or []),
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    "Read-only aggregate report data (JSON):\n"
                    f"{json.dumps(report_context, separators=(',', ':'))}"
                ),
            },
        ]
        payload = await self._create_completion(messages)
        answer = self._message_text(payload)
        if not answer or len(answer) > 4000:
            raise AIProviderFailure(
                self.name,
                502,
                "invalid_response",
                30,
                True,
            )
        return answer

    async def answer_with_tools(
        self,
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: AssistantToolExecutor,
    ) -> tuple[str, bool]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_instruction()},
            *self._history_messages(conversation_history),
            {"role": "user", "content": question},
        ]
        tools = _openai_tool_definitions()

        for _ in range(5):
            payload = await self._create_completion(
                messages,
                tools=tools,
            )
            message = self._first_message(payload)
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                raise AIProviderFailure(
                    self.name,
                    502,
                    "invalid_response",
                    30,
                    True,
                )
            if not tool_calls:
                answer = self._message_text(payload)
                if not answer or len(answer) > 4000:
                    raise AIProviderFailure(
                        self.name,
                        502,
                        "invalid_response",
                        30,
                        True,
                    )
                return answer, False

            for call in tool_calls:
                if not isinstance(call, dict):
                    raise AIProviderFailure(
                        self.name,
                        502,
                        "invalid_tool_call",
                        30,
                        True,
                    )
                function = call.get("function")
                if (
                    isinstance(function, dict)
                    and function.get("name") == "ask_user_for_clarification"
                ):
                    try:
                        clarification = ClarificationToolArguments.model_validate(
                            json.loads(function.get("arguments", "{}"))
                        )
                    except (TypeError, ValueError, ValidationError) as exc:
                        raise AIProviderFailure(
                            self.name,
                            502,
                            "invalid_clarification",
                            30,
                            True,
                        ) from exc
                    return clarification.question, True

            messages.append(message)
            for call in tool_calls:
                function = call.get("function")
                if not isinstance(function, dict):
                    raise AIProviderFailure(
                        self.name,
                        502,
                        "invalid_tool_call",
                        30,
                        True,
                    )
                name = function.get("name")
                arguments_json = function.get("arguments", "{}")
                call_id = call.get("id")
                if not isinstance(name, str) or not isinstance(call_id, str):
                    raise AIProviderFailure(
                        self.name,
                        502,
                        "invalid_tool_call",
                        30,
                        True,
                    )
                try:
                    arguments = json.loads(arguments_json)
                except (TypeError, ValueError) as exc:
                    raise AIProviderFailure(
                        self.name,
                        502,
                        "invalid_tool_arguments",
                        30,
                        True,
                    ) from exc
                if not isinstance(arguments, dict):
                    raise AIProviderFailure(
                        self.name,
                        502,
                        "invalid_tool_arguments",
                        30,
                        True,
                    )
                result = await execute_tool(name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": json.dumps(result, separators=(",", ":")),
                    }
                )

        raise AIProviderFailure(
            self.name,
            502,
            "tool_call_limit",
            30,
            True,
        )

    async def _create_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_completion_tokens": 1024,
        }
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = "auto"
            request_body["parallel_tool_calls"] = False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=5.0),
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self.url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
        except httpx.TimeoutException as exc:
            raise provider_timeout_failure(self.name) from exc
        except httpx.RequestError as exc:
            raise AIProviderFailure(
                self.name,
                503,
                "provider_failure",
                15,
                True,
            ) from exc
        if response.status_code != 200:
            raise provider_failure_from_response(self.name, response)
        try:
            payload = response.json()
            self._first_message(payload)
            return payload
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderFailure(
                self.name,
                502,
                "invalid_response",
                30,
                True,
            ) from exc

    @staticmethod
    def _history_messages(
        conversation_history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "assistant" if item["role"] == "assistant" else "user",
                "content": item["content"],
            }
            for item in conversation_history[-12:]
        ]

    @staticmethod
    def _first_message(payload: dict[str, Any]) -> dict[str, Any]:
        message = payload["choices"][0]["message"]
        if not isinstance(message, dict):
            raise TypeError("Provider returned an invalid message.")
        return message

    def _message_text(self, payload: dict[str, Any]) -> str:
        message = self._first_message(payload)
        if payload["choices"][0].get("finish_reason") == "length":
            raise AIProviderFailure(
                self.name,
                502,
                "incomplete_response",
                30,
                True,
            )
        content = message.get("content")
        return content.strip() if isinstance(content, str) else ""


def _openai_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": declaration["name"],
                "description": declaration["description"],
                "parameters": _lowercase_schema(declaration["parameters"]),
            },
        }
        for declaration in CHAT_TOOLS
    ]


def _lowercase_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {
            key: value.lower() if key == "type" and isinstance(value, str)
            else _lowercase_schema(value)
            for key, value in schema.items()
        }
    if isinstance(schema, list):
        return [_lowercase_schema(value) for value in schema]
    return schema


class AIProviderManager:
    def __init__(self, providers: list[AIProvider]) -> None:
        self.providers = providers
        self._health = {provider.name: ProviderHealth() for provider in providers}
        self._health_lock = Lock()

    async def answer(
        self,
        *,
        question: str,
        report_context: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        return await self._run(
            lambda provider: provider.answer(
                question=question,
                report_context=report_context,
                conversation_history=conversation_history,
            )
        )

    async def answer_with_tools(
        self,
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: AssistantToolExecutor,
    ) -> tuple[str, bool]:
        tool_cache: dict[tuple[str, str], dict[str, Any]] = {}

        async def execute_cached(
            name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            key = (name, json.dumps(arguments, sort_keys=True, separators=(",", ":")))
            if key not in tool_cache:
                tool_cache[key] = await execute_tool(name, arguments)
            return tool_cache[key]

        return await self._run(
            lambda provider: provider.answer_with_tools(
                question=question,
                conversation_history=conversation_history,
                execute_tool=execute_cached,
            )
        )

    async def _run(
        self,
        operation: Callable[[AIProvider], Awaitable[Any]],
    ) -> Any:
        configured = bool(self.providers)
        if not configured:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "FarmMate is not configured with an AI provider.",
                503,
            )

        available: list[AIProvider] = []
        now = time.monotonic()
        with self._health_lock:
            for provider in self.providers:
                state = self._health[provider.name]
                if not state.disabled and state.cooldown_until <= now:
                    available.append(provider)

        if not available:
            all_rate_limited = all(
                not self._health[provider.name].disabled
                and self._health[provider.name].cooldown_until > now
                for provider in self.providers
            )
            raise AppError(
                (
                    "AI_ASSISTANT_RATE_LIMITED"
                    if all_rate_limited
                    else "AI_ASSISTANT_UNAVAILABLE"
                ),
                (
                    "All AI providers are temporarily unavailable. Please wait and try again later."
                    if all_rate_limited
                    else "FarmMate is temporarily unavailable. Please contact support if the problem continues."
                ),
                429 if all_rate_limited else 503,
            )

        failures: list[AIProviderFailure] = []
        for index, provider in enumerate(available):
            try:
                result = await operation(provider)
            except AIProviderFailure as failure:
                failures.append(failure)
                self._mark_failure(failure)
                if not failure.retryable:
                    logger.error(
                        "ai_assistant_provider_non_retryable_failure",
                        extra={
                            "event": "ai_assistant_provider_non_retryable_failure",
                            "provider": failure.provider,
                            "status": failure.status_code,
                            "reason": failure.reason,
                            "provider_error_code": failure.provider_error_code,
                            "provider_error_type": failure.provider_error_type,
                            "provider_error_param": failure.provider_error_param,
                            "cooldown_seconds": failure.cooldown_seconds,
                        },
                    )
                    raise AppError(
                        "AI_ASSISTANT_PROVIDER_REJECTED_REQUEST",
                        "The AI provider rejected the request. Please check the provider configuration.",
                        502,
                    ) from failure
                if index + 1 < len(available):
                    logger.warning(
                        "ai_assistant_provider_failover",
                        extra={
                            "event": "ai_assistant_provider_failover",
                            "provider": provider.name,
                            "next_provider": available[index + 1].name,
                            "status": failure.status_code,
                            "reason": failure.reason,
                            "provider_error_code": failure.provider_error_code,
                            "provider_error_type": failure.provider_error_type,
                            "provider_error_param": failure.provider_error_param,
                            "cooldown_seconds": failure.cooldown_seconds,
                        },
                    )
                continue
            except AppError:
                raise
            self._mark_success(provider.name)
            return result

        if failures and all(failure.status_code == 429 for failure in failures):
            raise AppError(
                "AI_ASSISTANT_RATE_LIMITED",
                "All configured AI providers have reached their current limits. Please try again later.",
                429,
            )
        raise AppError(
            "AI_ASSISTANT_UNAVAILABLE",
            "FarmMate is temporarily unavailable. Please try again later.",
            503,
        )

    def _mark_failure(self, failure: AIProviderFailure) -> None:
        with self._health_lock:
            state = self._health[failure.provider]
            state.last_failure_kind = failure.reason
            state.last_status_code = failure.status_code or None
            if failure.status_code in {401, 403}:
                state.disabled = True
            if failure.retryable:
                state.cooldown_until = time.monotonic() + failure.cooldown_seconds
        logger.warning(
            "ai_assistant_provider_health_changed",
            extra={
                "event": "ai_assistant_provider_health_changed",
                "provider": failure.provider,
                "status": failure.status_code,
                "reason": failure.reason,
                "provider_error_code": failure.provider_error_code,
                "provider_error_type": failure.provider_error_type,
                "provider_error_param": failure.provider_error_param,
                "cooldown_seconds": failure.cooldown_seconds,
                "disabled": failure.status_code in {401, 403},
            },
        )

    def _mark_success(self, provider_name: str) -> None:
        with self._health_lock:
            state = self._health[provider_name]
            state.cooldown_until = 0
            state.disabled = False
            state.last_failure_kind = None
            state.last_status_code = None
            state.last_success_at = time.time()

    def health_snapshot(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._health_lock:
            return [
                {
                    "provider": provider.name,
                    "available": (
                        not self._health[provider.name].disabled
                        and self._health[provider.name].cooldown_until <= now
                    ),
                    "cooldown_seconds_remaining": max(
                        0,
                        round(
                            self._health[provider.name].cooldown_until - now,
                            1,
                        ),
                    ),
                    "last_failure_kind": self._health[
                        provider.name
                    ].last_failure_kind,
                    "last_status_code": self._health[
                        provider.name
                    ].last_status_code,
                    "last_success_at": self._health[
                        provider.name
                    ].last_success_at,
                }
                for provider in self.providers
            ]


@lru_cache(maxsize=1)
def get_ai_provider_manager() -> AIProviderManager:
    providers: list[AIProvider] = []
    if settings.groq_api_key is not None:
        providers.append(
            OpenAICompatibleProvider(
                name="groq",
                api_key=settings.groq_api_key.get_secret_value(),
                model=settings.groq_model,
                base_url="https://api.groq.com/openai/v1",
            )
        )
    if settings.gemini_api_key is not None:
        providers.append(GeminiClient())
    if settings.openrouter_api_key is not None:
        providers.append(
            OpenAICompatibleProvider(
                name="openrouter",
                api_key=settings.openrouter_api_key.get_secret_value(),
                model=settings.openrouter_model,
                base_url="https://openrouter.ai/api/v1",
            )
        )
    return AIProviderManager(providers)

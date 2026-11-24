import json
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_error_logger
from pydantic import ValidationError

from app.services.ai_assistant.contracts import (
    AssistantToolExecutor,
    ClarificationToolArguments,
)
from app.services.ai_assistant.prompts import (
    CHAT_TOOLS,
    PROFITABILITY_SYSTEM_INSTRUCTION,
    build_system_instruction,
)
from app.services.ai_provider_errors import (
    AIProviderFailure,
    provider_failure_from_response,
    provider_timeout_failure,
)

logger = get_error_logger()

class GeminiClient:
    name = "gemini"
    api_base_url = "https://generativelanguage.googleapis.com/v1beta/models"
    max_history_messages = 12
    max_tool_rounds = 4

    async def answer(
        self,
        *,
        question: str,
        report_context: dict[str, Any],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        if settings.gemini_api_key is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The AI assistant is not configured.",
                503,
            )

        model = quote(settings.gemini_model, safe="")
        url = f"{self.api_base_url}/{model}:generateContent"
        request_body = {
            "systemInstruction": {
                "parts": [{"text": PROFITABILITY_SYSTEM_INSTRUCTION}],
            },
            "contents": [
                {
                    "role": {"user": "user", "assistant": "model"}[message["role"]],
                    "parts": [{"text": message["content"]}],
                }
                for message in (conversation_history or [])[
                    -self.max_history_messages :
                ]
            ]
            + [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                f"Question:\n{question}\n\n"
                                "Read-only aggregate report data (JSON):\n"
                                f"{json.dumps(report_context, separators=(',', ':'))}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "text/plain",
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=5.0),
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": settings.gemini_api_key.get_secret_value(),
                    },
                    json=request_body,
                )
        except httpx.TimeoutException as exc:
            logger.warning(
                "ai_assistant_provider_timeout",
                extra={"event": "ai_assistant_provider_timeout"},
            )
            raise provider_timeout_failure("gemini") from exc
        except httpx.RequestError as exc:
            logger.warning(
                "ai_assistant_provider_unavailable",
                extra={"event": "ai_assistant_provider_unavailable"},
            )
            raise AIProviderFailure(
                "gemini",
                503,
                "provider_failure",
                15,
                True,
            ) from exc

        if response.status_code != 200:
            failure = provider_failure_from_response("gemini", response)
            logger.warning(
                "ai_assistant_provider_rejected_request",
                extra={
                    "event": "ai_assistant_provider_rejected_request",
                    "status": response.status_code,
                    "reason": failure.reason,
                },
            )
            raise failure

        try:
            payload = response.json()
            candidate = payload["candidates"][0]
            if candidate.get("finishReason") == "MAX_TOKENS":
                logger.warning(
                    "ai_assistant_response_truncated",
                    extra={"event": "ai_assistant_response_truncated"},
                )
                raise AIProviderFailure(
                    "gemini",
                    502,
                    "incomplete_response",
                    30,
                    True,
                )
            parts = candidate["content"]["parts"]
            answer = "".join(
                part["text"]
                for part in parts
                if isinstance(part.get("text"), str) and not part.get("thought")
            )
        except AIProviderFailure:
            raise
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning(
                "ai_assistant_invalid_provider_response",
                extra={"event": "ai_assistant_invalid_provider_response"},
            )
            raise AIProviderFailure(
                "gemini",
                502,
                "invalid_response",
                30,
                True,
            ) from exc

        if not isinstance(answer, str) or not answer.strip() or len(answer) > 4000:
            raise AIProviderFailure("gemini", 502, "invalid_response", 30, True)
        return answer.strip()

    async def answer_with_tools(
        self,
        *,
        question: str,
        conversation_history: list[dict[str, str]],
        execute_tool: AssistantToolExecutor,
    ) -> tuple[str, bool]:
        if settings.gemini_api_key is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The AI assistant is not configured.",
                503,
            )

        model = quote(settings.gemini_model, safe="")
        url = f"{self.api_base_url}/{model}:generateContent"
        contents: list[dict[str, Any]] = [
            {
                "role": {"user": "user", "assistant": "model"}[message["role"]],
                "parts": [{"text": message["content"]}],
            }
            for message in conversation_history[-self.max_history_messages :]
        ]
        contents.append({"role": "user", "parts": [{"text": question}]})
        request_body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": build_system_instruction()}]},
            "contents": contents,
            "tools": [{"functionDeclarations": CHAT_TOOLS}],
            "toolConfig": {
                "functionCallingConfig": {"mode": "AUTO"}
            },
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "text/plain",
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }

        for tool_round in range(self.max_tool_rounds + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(20.0, connect=5.0),
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        url,
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": settings.gemini_api_key.get_secret_value(),
                        },
                        json=request_body,
                    )
            except httpx.TimeoutException as exc:
                logger.warning(
                    "ai_assistant_provider_timeout",
                    extra={"event": "ai_assistant_provider_timeout"},
                )
                raise provider_timeout_failure("gemini") from exc
            except httpx.RequestError as exc:
                logger.warning(
                    "ai_assistant_provider_unavailable",
                    extra={"event": "ai_assistant_provider_unavailable"},
                )
                raise AIProviderFailure(
                    "gemini",
                    503,
                    "provider_failure",
                    15,
                    True,
                ) from exc

            if response.status_code != 200:
                failure = provider_failure_from_response("gemini", response)
                logger.warning(
                    "ai_assistant_provider_rejected_request",
                    extra={
                        "event": "ai_assistant_provider_rejected_request",
                        "status": response.status_code,
                        "reason": failure.reason,
                    },
                )
                raise failure

            try:
                payload = response.json()
                candidate = payload["candidates"][0]
                if candidate.get("finishReason") == "MAX_TOKENS":
                    raise AIProviderFailure(
                        "gemini",
                        502,
                        "incomplete_response",
                        30,
                        True,
                    )
                model_content = candidate["content"]
                parts = model_content["parts"]
                function_calls = [
                    part["functionCall"]
                    for part in parts
                    if isinstance(part.get("functionCall"), dict)
                ]
                text = "".join(
                    part["text"]
                    for part in parts
                    if isinstance(part.get("text"), str)
                    and not part.get("thought")
                ).strip()
            except AIProviderFailure:
                raise
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                logger.warning(
                    "ai_assistant_invalid_provider_response",
                    extra={"event": "ai_assistant_invalid_provider_response"},
                )
                raise AIProviderFailure(
                    "gemini",
                    502,
                    "invalid_response",
                    30,
                    True,
                ) from exc

            if not function_calls:
                if not text or len(text) > 4000:
                    raise AIProviderFailure(
                        "gemini",
                        502,
                        "invalid_response",
                        30,
                        True,
                    )
                return text, False

            for call in function_calls:
                if call.get("name") == "ask_user_for_clarification":
                    arguments = call.get("args", {})
                    try:
                        clarification = ClarificationToolArguments.model_validate(
                            arguments
                        )
                    except ValidationError as exc:
                        raise AIProviderFailure(
                            "gemini",
                            502,
                            "invalid_clarification",
                            30,
                            True,
                        ) from exc
                    return clarification.question, True

            if tool_round == self.max_tool_rounds:
                raise AIProviderFailure(
                    "gemini",
                    502,
                    "tool_call_limit",
                    30,
                    True,
                )

            contents.append(model_content)
            for call in function_calls:
                name = call.get("name")
                arguments = call.get("args", {})
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    raise AIProviderFailure(
                        "gemini",
                        502,
                        "invalid_tool_call",
                        30,
                        True,
                    )
                if name not in {tool["name"] for tool in CHAT_TOOLS}:
                    result = {"error": "Unsupported read capability."}
                else:
                    result = await execute_tool(name, arguments)
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": name,
                                    "response": result,
                                }
                            }
                        ],
                    }
                )

        raise AIProviderFailure("gemini", 502, "tool_call_limit", 30, True)

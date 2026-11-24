import re
from datetime import date
from typing import Any
from uuid import UUID

from app.core.exceptions import AppError, ResourceNotFoundError
from app.models.farm import Farm
from app.services.ai_assistant.gemini import GeminiClient
from app.services.ai_assistant.service_context import AssistantServiceContext
from app.services.ai_assistant.tool_execution import (
    AssistantToolExecutionContext,
    ChatToolExecutor,
)

class FarmAssistantChatMixin(AssistantServiceContext):
    async def answer_chat_question(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        question: str,
        conversation_id: UUID | None = None,
        source_route: str | None = None,
        farm: Farm | None = None,
    ) -> tuple[
        UUID,
        str,
        bool,
        list[str],
        date | None,
        date | None,
        list[dict[str, str]],
    ]:
        if farm is not None and farm.id != farm_id:
            raise ResourceNotFoundError("Farm not found.")
        account_ledger_service = self.account_ledger_service
        if account_ledger_service is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The assistant's read tools are not configured.",
                503,
            )
        answer_with_tools = getattr(
            self.provider_manager,
            "answer_with_tools",
            None,
        )
        if answer_with_tools is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The assistant's read tools are not configured.",
                503,
            )

        conversation = None
        previous_expense_period: tuple[date, date] | None = None
        previous_report_is_profitability = False
        if conversation_id is not None:
            conversation = await self.conversation_repository.get_for_user(
                conversation_id=conversation_id,
                farm_id=farm_id,
                user_id=user_id,
            )
            if conversation is None:
                raise ResourceNotFoundError("Assistant conversation not found.")
            previous_messages = await self.conversation_repository.list_messages(
                conversation.id
            )
            latest_assistant_message = next(
                (
                    message
                    for message in reversed(previous_messages)
                    if message.role == "assistant"
                ),
                None,
            )
            if (
                latest_assistant_message is not None
                and latest_assistant_message.from_date is not None
                and latest_assistant_message.to_date is not None
                and re.search(
                    r"\b(expenses?|costs?|profit(?:ability)?)\b",
                    latest_assistant_message.content,
                    re.IGNORECASE,
                )
            ):
                previous_expense_period = (
                    latest_assistant_message.from_date,
                    latest_assistant_message.to_date,
                )
                previous_report_is_profitability = bool(
                    re.search(
                        r"\b(profitability|net profit|gross sales)\b",
                        latest_assistant_message.content,
                        re.IGNORECASE,
                    )
                )
            conversation_history = [
                {"role": message.role, "content": message.content}
                for message in previous_messages[-GeminiClient.max_history_messages :]
            ]
        else:
            conversation_history = []

        data_scopes: list[str] = []
        used_from_date: date | None = None
        used_to_date: date | None = None
        navigation_destination: str | None = None
        verified_hrefs: set[str] = set()
        model_question = self._add_source_route_context(question, source_route)
        if self._is_expense_detail_follow_up(question) and previous_expense_period:
            model_question = (
                f"[Expense report follow-up context: the preceding expense or "
                f"profitability report covered {previous_expense_period[0]} through "
                f"{previous_expense_period[1]}. Reuse this period when finding its "
                f"underlying expense records unless the user states another period.]\n"
                f"{model_question}"
            )

        tool_context = AssistantToolExecutionContext(
            service=self,
            farm=farm,
            farm_id=farm_id,
            question=question,
            previous_expense_period=previous_expense_period,
            previous_report_is_profitability=previous_report_is_profitability,
            data_scopes=data_scopes,
        )
        tool_executor = ChatToolExecutor(tool_context)

        async def execute_tool_with_verified_hrefs(
            name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal used_from_date, used_to_date, navigation_destination
            result = await tool_executor.execute(name, arguments)
            used_from_date = tool_context.used_from_date
            used_to_date = tool_context.used_to_date
            navigation_destination = tool_context.navigation_destination
            verified_hrefs.update(self._collect_assistant_hrefs(result))
            return result

        answer, needs_clarification = await answer_with_tools(
            question=model_question,
            conversation_history=conversation_history,
            execute_tool=execute_tool_with_verified_hrefs,
        )
        answer = self._remove_unverified_assistant_links(answer, verified_hrefs)
        if conversation is None:
            conversation = await self.conversation_repository.create(
                farm_id=farm_id,
                user_id=user_id,
                title=question,
            )
        await self.conversation_repository.add_exchange(
            conversation=conversation,
            question=question,
            answer=answer,
            from_date=used_from_date,
            to_date=used_to_date,
        )
        await self.unit_of_work.commit()
        suggested_replies: list[dict[str, str]] = []
        explicit_walkthrough = re.search(
            r"\b(step[- ]by[- ]step|walk me through|guide me through|"
            r"every step|each step)\b",
            question,
            re.IGNORECASE,
        )
        workflow_detail_follow_up = {
            "chicken_purchase": r"\b(arrival|receive|receipt)\b",
            "chicken_sale": r"\b(deliver|delivery|payment|discount|balance)\b",
            "record_chicken_loss": (
                r"\b(reason|disease|predator|injury|accident|culling|missing)\b"
            ),
            "chicken_movement": (
                r"\b(source|destination|capacity|space|batch|available)\b"
            ),
            "egg_collection": r"\b(block|unit|date|time|quantity|notes)\b",
            "egg_loss": r"\b(reason|stock|quantity|date|available)\b",
            "egg_sale": r"\b(payment|customer|balance|price|stock|quantity)\b",
            "sale_adjustments": r"\b(return|refund|settlement|payment)\b",
            "purchase_adjustments": (
                r"\b(return|refund|replacement|settlement|payment)\b"
            ),
        }.get(navigation_destination or "")
        is_detail_follow_up = (
            workflow_detail_follow_up is not None
            and re.search(workflow_detail_follow_up, question, re.IGNORECASE)
            is not None
        )
        workflow_replies = {
            "chicken_purchase": [
                (
                    "Guide me step by step",
                    "Guide me step by step through the chicken purchase form.",
                ),
                (
                    "Explain recording an arrival",
                    "How do I record the chicken arrival after saving a purchase?",
                ),
            ],
            "chicken_sale": [
                (
                    "Guide me step by step",
                    "Guide me step by step through the chicken sale form.",
                ),
                (
                    "Explain delivery",
                    "How do I record a chicken delivery after a sale?",
                ),
            ],
            "record_chicken_loss": [
                (
                    "Guide me step by step",
                    "Guide me step by step through recording a chicken loss.",
                ),
                (
                    "Explain loss reasons",
                    "What loss reasons can I choose when recording chicken losses?",
                ),
            ],
            "chicken_movement": [
                (
                    "Guide me step by step",
                    "Guide me step by step through moving chickens between blocks.",
                ),
                (
                    "Check capacity rules",
                    "What should I check if the destination block lacks capacity?",
                ),
            ],
            "eggs": [
                ("Record egg collection", "How do I record an egg collection?"),
                ("Sell eggs", "How do I record an egg sale?"),
                ("Record egg loss", "How do I record an egg loss?"),
            ],
            "egg_collection": [
                (
                    "Guide me step by step",
                    "Guide me step by step through recording an egg collection.",
                ),
                (
                    "Explain units and blocks",
                    "How do units and source blocks work in egg collection?",
                ),
            ],
            "egg_loss": [
                (
                    "Guide me step by step",
                    "Guide me step by step through recording an egg loss.",
                ),
                (
                    "Explain loss reasons",
                    "What reasons can I choose when recording egg loss?",
                ),
            ],
            "egg_sale": [
                (
                    "Guide me step by step",
                    "Guide me step by step through recording an egg sale.",
                ),
                (
                    "Explain payment options",
                    "How do payment and customer balances work for an egg sale?",
                ),
            ],
            "sale_adjustments": [
                (
                    "Help me choose the right action",
                    "How do I choose between a sale return, refund, and settlement?",
                ),
                (
                    "Trace a sale",
                    "How can I review all activity linked to a sale?",
                ),
            ],
            "purchase_adjustments": [
                (
                    "Help me choose the right action",
                    (
                        "How do I choose between a purchase return, supplier "
                        "refund, replacement, and settlement?"
                    ),
                ),
                (
                    "Trace a purchase",
                    "How can I review all activity linked to a purchase?",
                ),
            ],
        }
        replies = workflow_replies.get(navigation_destination or "")
        if (
            replies is not None
            and not explicit_walkthrough
            and not is_detail_follow_up
        ):
            suggested_replies = [
                {"label": label, "question": suggested_question}
                for label, suggested_question in replies
            ]
        return (
            conversation.id,
            answer,
            needs_clarification,
            list(dict.fromkeys(data_scopes)),
            used_from_date,
            used_to_date,
            suggested_replies,
        )

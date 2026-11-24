from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.assistant_conversation import AssistantMessage
from app.repositories.assistant_conversation_repository import (
    AssistantConversationRepository,
)


@pytest.mark.asyncio
async def test_add_exchange_persists_question_before_answer():
    class FakeSession:
        messages: list[AssistantMessage] = []

        def add_all(self, messages: list[AssistantMessage]) -> None:
            self.messages = messages

        async def flush(self) -> None:
            pass

    session = FakeSession()
    repository = AssistantConversationRepository(session)  # type: ignore[arg-type]
    conversation = SimpleNamespace(id=uuid4(), updated_at=None)

    await repository.add_exchange(
        conversation=conversation,
        question="How many eggs were collected?",
        answer="You collected 24 eggs.",
    )

    question, answer = session.messages
    assert question.role == "user"
    assert answer.role == "assistant"
    assert question.created_at < answer.created_at
    assert isinstance(question.created_at, datetime)
    assert conversation.updated_at is not None


@pytest.mark.asyncio
async def test_list_messages_orders_user_first_when_exchange_timestamps_match():
    class FakeScalars:
        def all(self) -> list[AssistantMessage]:
            return []

    class FakeResult:
        def scalars(self) -> FakeScalars:
            return FakeScalars()

    class FakeSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    repository = AssistantConversationRepository(session)  # type: ignore[arg-type]

    await repository.list_messages(uuid4())

    assert session.statement is not None
    sql = str(session.statement.compile())
    order_by = sql.split("ORDER BY", maxsplit=1)[1]
    assert "assistant_messages.created_at" in order_by
    assert "CASE WHEN" in order_by
    assert order_by.index("CASE WHEN") < order_by.index("assistant_messages.id")
    assert "assistant_messages.role" in order_by

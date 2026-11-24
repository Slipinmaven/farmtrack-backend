from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant_conversation import AssistantConversation, AssistantMessage


class AssistantConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        title: str,
    ) -> AssistantConversation:
        conversation = AssistantConversation(
            farm_id=farm_id,
            user_id=user_id,
            title=title[:120],
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_for_user(
        self,
        *,
        conversation_id: UUID,
        farm_id: UUID,
        user_id: UUID,
    ) -> AssistantConversation | None:
        result = await self.session.execute(
            select(AssistantConversation).where(
                AssistantConversation.id == conversation_id,
                AssistantConversation.farm_id == farm_id,
                AssistantConversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> list[AssistantConversation]:
        result = await self.session.execute(
            select(AssistantConversation)
            .where(
                AssistantConversation.farm_id == farm_id,
                AssistantConversation.user_id == user_id,
            )
            .order_by(
                AssistantConversation.updated_at.desc(),
                AssistantConversation.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_messages(
        self,
        conversation_id: UUID,
    ) -> list[AssistantMessage]:
        result = await self.session.execute(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation_id)
            .order_by(
                AssistantMessage.created_at,
                case(
                    (AssistantMessage.role == "user", 0),
                    else_=1,
                ),
                AssistantMessage.id,
            )
        )
        return list(result.scalars().all())

    async def add_exchange(
        self,
        *,
        conversation: AssistantConversation,
        question: str,
        answer: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> None:
        user_message_created_at = datetime.now(timezone.utc)
        self.session.add_all(
            [
                AssistantMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content=question,
                    from_date=from_date,
                    to_date=to_date,
                    created_at=user_message_created_at,
                ),
                AssistantMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=answer,
                    from_date=from_date,
                    to_date=to_date,
                    created_at=user_message_created_at + timedelta(microseconds=1),
                ),
            ]
        )
        conversation.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def delete(self, conversation: AssistantConversation) -> None:
        await self.session.delete(conversation)
        await self.session.flush()

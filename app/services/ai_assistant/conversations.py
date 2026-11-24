from uuid import UUID

from app.core.exceptions import ResourceNotFoundError
from app.models.assistant_conversation import AssistantConversation, AssistantMessage
from app.services.ai_assistant.service_context import AssistantServiceContext


class FarmAssistantConversationMixin(AssistantServiceContext):
    async def list_conversations(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> list[AssistantConversation]:
        return await self.conversation_repository.list_for_user(
            farm_id=farm_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

    async def get_conversation(
        self,
        *,
        conversation_id: UUID,
        farm_id: UUID,
        user_id: UUID,
    ) -> tuple[AssistantConversation, list[AssistantMessage]]:
        conversation = await self.conversation_repository.get_for_user(
            conversation_id=conversation_id,
            farm_id=farm_id,
            user_id=user_id,
        )
        if conversation is None:
            raise ResourceNotFoundError("Assistant conversation not found.")
        messages = await self.conversation_repository.list_messages(conversation.id)
        return conversation, messages

    async def rename_conversation(
        self,
        *,
        conversation_id: UUID,
        farm_id: UUID,
        user_id: UUID,
        title: str,
    ) -> AssistantConversation:
        conversation = await self.conversation_repository.get_for_user(
            conversation_id=conversation_id,
            farm_id=farm_id,
            user_id=user_id,
        )
        if conversation is None:
            raise ResourceNotFoundError("Assistant conversation not found.")
        conversation.title = title
        await self.unit_of_work.commit()
        return conversation

    async def delete_conversation(
        self,
        *,
        conversation_id: UUID,
        farm_id: UUID,
        user_id: UUID,
    ) -> None:
        conversation = await self.conversation_repository.get_for_user(
            conversation_id=conversation_id,
            farm_id=farm_id,
            user_id=user_id,
        )
        if conversation is None:
            raise ResourceNotFoundError("Assistant conversation not found.")
        await self.conversation_repository.delete(conversation)
        await self.unit_of_work.commit()

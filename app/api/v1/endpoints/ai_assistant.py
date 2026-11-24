from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies.auth import get_current_user, require_super_admin
from app.dependencies.farm import get_owned_farm
from app.models.farm import Farm
from app.models.user import User
from app.presentation.dependencies.services import get_farm_assistant_service
from app.schemas.ai_assistant import (
    AssistantAnswerResponse,
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantConversationDeleteResponse,
    AssistantConversationListResponse,
    AssistantConversationRenameRequest,
    AssistantConversationResponse,
    AssistantConversationSummary,
    AssistantMessageResponse,
    ProfitabilityQuestionRequest,
)
from app.services.ai_assistant_service import FarmAssistantService

router = APIRouter(
    prefix="/farms/{farm_id}/assistant",
    tags=["AI Assistant"],
    dependencies=[Depends(require_super_admin)],
)


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    request: AssistantChatRequest,
    response: Response,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FarmAssistantService, Depends(get_farm_assistant_service)],
) -> AssistantChatResponse:
    response.headers["Cache-Control"] = "no-store"
    (
        conversation_id,
        answer,
        needs_clarification,
        data_scopes,
        from_date,
        to_date,
        suggested_replies,
    ) = await service.answer_chat_question(
        farm_id=farm.id,
        user_id=current_user.id,
        question=request.question,
        conversation_id=request.conversation_id,
        source_route=request.source_route,
        farm=farm,
    )
    return AssistantChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        needs_clarification=needs_clarification,
        data_scopes=data_scopes,
        suggested_replies=suggested_replies,
        from_date=from_date,
        to_date=to_date,
    )


@router.post("/profitability", response_model=AssistantAnswerResponse)
async def ask_about_profitability(
    request: ProfitabilityQuestionRequest,
    response: Response,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FarmAssistantService, Depends(get_farm_assistant_service)],
) -> AssistantAnswerResponse:
    response.headers["Cache-Control"] = "no-store"
    conversation_id, answer = await service.answer_profitability_question(
        farm_id=farm.id,
        user_id=current_user.id,
        question=request.question,
        from_date=request.from_date,
        to_date=request.to_date,
        conversation_id=request.conversation_id,
    )
    return AssistantAnswerResponse(
        conversation_id=conversation_id,
        answer=answer,
        from_date=request.from_date,
        to_date=request.to_date,
    )


@router.get(
    "/conversations",
    response_model=AssistantConversationListResponse,
)
async def list_conversations(
    response: Response,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FarmAssistantService, Depends(get_farm_assistant_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> AssistantConversationListResponse:
    response.headers["Cache-Control"] = "no-store"
    conversations = await service.list_conversations(
        farm_id=farm.id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    return AssistantConversationListResponse(
        items=[
            AssistantConversationSummary.model_validate(
                conversation,
                from_attributes=True,
            )
            for conversation in conversations
        ]
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=AssistantConversationResponse,
)
async def get_conversation(
    conversation_id: UUID,
    response: Response,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FarmAssistantService, Depends(get_farm_assistant_service)],
) -> AssistantConversationResponse:
    response.headers["Cache-Control"] = "no-store"
    conversation, messages = await service.get_conversation(
        conversation_id=conversation_id,
        farm_id=farm.id,
        user_id=current_user.id,
    )
    return AssistantConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            AssistantMessageResponse.model_validate(message, from_attributes=True)
            for message in messages
        ],
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=AssistantConversationSummary,
)
async def rename_conversation(
    conversation_id: UUID,
    request: AssistantConversationRenameRequest,
    response: Response,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FarmAssistantService, Depends(get_farm_assistant_service)],
) -> AssistantConversationSummary:
    response.headers["Cache-Control"] = "no-store"
    conversation = await service.rename_conversation(
        conversation_id=conversation_id,
        farm_id=farm.id,
        user_id=current_user.id,
        title=request.title,
    )
    return AssistantConversationSummary.model_validate(
        conversation,
        from_attributes=True,
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=AssistantConversationDeleteResponse,
)
async def delete_conversation(
    conversation_id: UUID,
    response: Response,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FarmAssistantService, Depends(get_farm_assistant_service)],
) -> AssistantConversationDeleteResponse:
    response.headers["Cache-Control"] = "no-store"
    await service.delete_conversation(
        conversation_id=conversation_id,
        farm_id=farm.id,
        user_id=current_user.id,
    )
    return AssistantConversationDeleteResponse()

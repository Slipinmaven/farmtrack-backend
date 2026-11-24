import re
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+\d{8,15}|0\d{9,14}|\d{3,5}[ .()-]\d{3,5}[ .()-]\d{3,5})(?!\w)"
)


class ProfitabilityQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    from_date: date
    to_date: date
    conversation_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be blank.")
        if _EMAIL_PATTERN.search(normalized) or _PHONE_PATTERN.search(normalized):
            raise ValueError(
                "Do not include email addresses or phone numbers in assistant questions."
            )
        return normalized

    @model_validator(mode="after")
    def validate_report_period(self) -> "ProfitabilityQuestionRequest":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date.")
        if (self.to_date - self.from_date).days > 366:
            raise ValueError("The report period must not exceed 367 days.")
        return self


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None
    source_route: str | None = Field(default=None, max_length=120)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be blank.")
        if _EMAIL_PATTERN.search(normalized) or _PHONE_PATTERN.search(normalized):
            raise ValueError(
                "Do not include email addresses or phone numbers in assistant questions."
            )
        return normalized

    @field_validator("source_route")
    @classmethod
    def validate_source_route(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not value.startswith("/")
            or value.startswith("//")
            or any(character in value for character in ("?", "#", "\\"))
            or ".." in value.split("/")
            or any(character.isspace() for character in value)
        ):
            raise ValueError("source_route must be an in-app route path.")
        return value


class AssistantSuggestedReply(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=200)


class AssistantAnswerResponse(BaseModel):
    conversation_id: UUID
    answer: str
    from_date: date
    to_date: date
    data_scope: str = "profitability_summary"


class AssistantChatResponse(BaseModel):
    conversation_id: UUID
    answer: str
    needs_clarification: bool = False
    data_scopes: list[str] = Field(default_factory=list)
    suggested_replies: list[AssistantSuggestedReply] = Field(default_factory=list)
    from_date: date | None = None
    to_date: date | None = None


class AssistantConversationSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class AssistantConversationRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Conversation title must not be blank.")
        return normalized


class AssistantMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    from_date: date | None = None
    to_date: date | None = None
    created_at: datetime


class AssistantConversationResponse(AssistantConversationSummary):
    messages: list[AssistantMessageResponse]


class AssistantConversationListResponse(BaseModel):
    items: list[AssistantConversationSummary]


class AssistantConversationDeleteResponse(BaseModel):
    deleted: bool = True

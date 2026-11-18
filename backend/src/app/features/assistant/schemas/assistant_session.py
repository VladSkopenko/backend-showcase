import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.features.assistant.enums import AssistantMessageRole


class AssistantSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class AssistantMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: AssistantMessageRole
    text: str
    created_at: datetime


class AssistantSessionDetailResponse(AssistantSessionResponse):
    messages: list[AssistantMessageResponse]

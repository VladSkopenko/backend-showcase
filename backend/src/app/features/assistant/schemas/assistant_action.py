import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.features.assistant.enums import AssistantActionStatus


class AssistantCardFieldResponse(BaseModel):
    label: str
    value: str


class AssistantCardResponse(BaseModel):
    title: str
    fields: list[AssistantCardFieldResponse]
    notice: str | None
    confirm_label: str


class AssistantActionErrorResponse(BaseModel):
    code: str
    message: str


class AssistantActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: AssistantActionStatus
    card: AssistantCardResponse
    created_at: datetime
    expires_at: datetime
    result: dict[str, Any] | None
    error: AssistantActionErrorResponse | None

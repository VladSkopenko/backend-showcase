import uuid
from dataclasses import dataclass
from datetime import datetime

from app.features.assistant.dto.assistant_action_view import AssistantActionView
from app.features.assistant.enums import AssistantMessageRole


@dataclass(frozen=True)
class AssistantMessageView:
    id: uuid.UUID
    role: AssistantMessageRole
    text: str
    created_at: datetime
    action: AssistantActionView | None

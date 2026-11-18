import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.features.assistant.dto.assistant_message_view import AssistantMessageView


@dataclass(frozen=True)
class AssistantSessionView:
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: Sequence[AssistantMessageView]

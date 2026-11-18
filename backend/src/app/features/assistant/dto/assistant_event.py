import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.features.assistant.dto.assistant_action_view import AssistantActionView


@dataclass(frozen=True)
class AssistantEvent:
    """One event of a streamed turn; the API layer encodes it for the wire."""

    THINKING = "thinking"
    CHUNK = "chunk"
    ACTION = "action"
    DONE = "done"
    ERROR = "error"

    name: str
    data: Mapping[str, Any]

    @classmethod
    def thinking(cls) -> AssistantEvent:
        return cls(cls.THINKING, {})

    @classmethod
    def chunk(cls, text: str) -> AssistantEvent:
        return cls(cls.CHUNK, {"text": text})

    @classmethod
    def action(cls, view: AssistantActionView) -> AssistantEvent:
        return cls(
            cls.ACTION,
            {
                "id": view.id,
                "kind": view.kind,
                "status": view.status.value,
                "card": view.card,
                "created_at": view.created_at,
                "expires_at": view.expires_at,
                "result": view.result,
                "error": view.error,
            },
        )

    @classmethod
    def done(cls, *, message_id: uuid.UUID | None, created_at: datetime | None) -> AssistantEvent:
        return cls(cls.DONE, {"message_id": message_id, "created_at": created_at})

    @classmethod
    def error(cls, *, code: str, message: str) -> AssistantEvent:
        return cls(cls.ERROR, {"code": code, "message": message})

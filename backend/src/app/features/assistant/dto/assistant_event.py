import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AssistantEvent:
    """One event of a streamed turn; the API layer encodes it for the wire."""

    THINKING = "thinking"
    CHUNK = "chunk"
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
    def done(cls, *, message_id: uuid.UUID, created_at: datetime) -> AssistantEvent:
        return cls(cls.DONE, {"message_id": message_id, "created_at": created_at})

    @classmethod
    def error(cls, *, code: str, message: str) -> AssistantEvent:
        return cls(cls.ERROR, {"code": code, "message": message})

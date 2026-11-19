import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.features.assistant.enums import AssistantActionStatus


@dataclass(frozen=True)
class AssistantActionView:
    id: uuid.UUID
    kind: str
    status: AssistantActionStatus
    card: Mapping[str, Any]
    created_at: datetime
    expires_at: datetime
    result: Mapping[str, Any] | None
    error: Mapping[str, Any] | None

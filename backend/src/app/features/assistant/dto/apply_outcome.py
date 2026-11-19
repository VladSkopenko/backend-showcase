from dataclasses import dataclass

from app.features.assistant.dto.assistant_action_view import AssistantActionView


@dataclass(frozen=True)
class ApplyOutcome:
    action: AssistantActionView
    replayed: bool

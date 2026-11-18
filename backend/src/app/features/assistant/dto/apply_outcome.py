from dataclasses import dataclass

from app.features.assistant.dto.assistant_action_view import AssistantActionView


@dataclass(frozen=True)
class ApplyOutcome:
    """`replayed` is an apply that found the action already applied and executed nothing."""

    action: AssistantActionView
    replayed: bool

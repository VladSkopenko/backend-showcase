import uuid
from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.assistant.dto import AssistantActionView
from app.features.assistant.enums import AssistantActionStatus, AssistantMessageRole
from app.features.assistant.models import AssistantMessage
from app.features.assistant.repositories import AssistantMessageRepository
from app.features.assistant.services.assistant_action_service import AssistantActionService


class ModelHistoryBuilder:
    """The session's latest messages as the model sees them, each proposal's status appended."""

    def __init__(self, session: AsyncSession, *, action_ttl_hours: int) -> None:
        self._messages = AssistantMessageRepository(session)
        self._actions = AssistantActionService(session, action_ttl_hours=action_ttl_hours)

    async def build(self, *, session_id: uuid.UUID, limit: int, now: datetime) -> list[BaseMessage]:
        history = await self._messages.list_last_for_session(session_id=session_id, limit=limit)
        actions = await self._actions.views_for_messages(
            message_ids=[message.id for message in history], now=now
        )
        return [self._to_model_message(message, actions.get(message.id)) for message in history]

    @staticmethod
    def _to_model_message(
        message: AssistantMessage, action: AssistantActionView | None
    ) -> BaseMessage:
        if message.role is AssistantMessageRole.USER:
            return HumanMessage(message.text)
        if action is None:
            return AIMessage(message.text)
        outcome = action.status.value
        if action.status is AssistantActionStatus.FAILED and action.error is not None:
            outcome = f"{outcome} {action.error['code']}"
        return AIMessage(f"{message.text}\n[Proposed {action.kind}: {outcome}]")

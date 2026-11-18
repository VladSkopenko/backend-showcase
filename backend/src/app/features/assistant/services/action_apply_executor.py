import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai_tools import ActionApplier, ActionContext
from app.common.errors import DomainError
from app.features.assistant.dto import ApplyOutcome
from app.features.assistant.enums import AssistantActionStatus
from app.features.assistant.repositories import AssistantActionRepository
from app.features.assistant.services.assistant_action_service import AssistantActionService
from app.features.assistant.services.exceptions import (
    AssistantActionNotFoundError,
    AssistantActionNotPendingError,
)


class ActionApplyExecutor:
    """Claims a pending action and runs its applier in the caller's transaction.

    The applier runs inside a savepoint: a domain error that aborted a flush rolls back to it,
    and the transaction still records the action as failed.
    """

    UNKNOWN_ACTION_CODE = "UNKNOWN_ACTION"
    UNKNOWN_ACTION_MESSAGE = "This kind of card can no longer be applied."

    def __init__(self, session: AsyncSession, *, appliers: Mapping[str, ActionApplier]) -> None:
        self._session = session
        self._actions = AssistantActionRepository(session)
        self._appliers = appliers

    async def apply(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, action_id: uuid.UUID, now: datetime
    ) -> ApplyOutcome:
        action = await self._actions.get_for_user(
            action_id=action_id, session_id=session_id, user_id=user_id
        )
        if action is None:
            raise AssistantActionNotFoundError()
        if not await self._actions.claim(action_id=action_id, now=now):
            current = await self._actions.get_for_user(
                action_id=action_id, session_id=session_id, user_id=user_id
            )
            if current is None:
                raise AssistantActionNotFoundError()
            if current.status is not AssistantActionStatus.APPLIED:
                raise AssistantActionNotPendingError()
            return ApplyOutcome(action=AssistantActionService.view(current, now=now), replayed=True)
        applier = self._appliers.get(action.kind)
        context = ActionContext(session=self._session, user_id=user_id, payload=action.payload)
        result: dict[str, Any] | None = None
        error: dict[str, str] | None = None
        if applier is None:
            error = {"code": self.UNKNOWN_ACTION_CODE, "message": self.UNKNOWN_ACTION_MESSAGE}
        else:
            try:
                async with self._session.begin_nested():
                    result = await applier.apply(context)
            except DomainError as failure:
                error = {"code": failure.code, "message": failure.message}
        claimed = await self._actions.get_for_user(
            action_id=action_id, session_id=session_id, user_id=user_id
        )
        if claimed is None:
            raise AssistantActionNotFoundError()
        if error is None:
            claimed.result = result
        else:
            claimed.status = AssistantActionStatus.FAILED
            claimed.error = error
        await self._actions.flush()
        return ApplyOutcome(action=AssistantActionService.view(claimed, now=now), replayed=False)

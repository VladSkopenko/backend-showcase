import dataclasses
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.common.ai_tools import Proposal
from app.features.assistant.dto import AssistantActionView
from app.features.assistant.enums import AssistantActionStatus
from app.features.assistant.models import AssistantAction
from app.features.assistant.repositories import (
    AssistantActionRepository,
    AssistantSessionRepository,
)
from app.features.assistant.services.exceptions import (
    AssistantActionNotFoundError,
    AssistantActionNotPendingError,
)


class AssistantActionService:
    """Stores the proposals of turns and shows, reads and cancels them.

    Expiry is derived on read: a pending row past `expires_at` is shown as expired and only a
    newer proposal writes `EXPIRED`, so a refusing path writes nothing.
    """

    def __init__(self, session: AsyncSession, *, action_ttl_hours: int) -> None:
        self._actions = AssistantActionRepository(session)
        self._sessions = AssistantSessionRepository(session)
        self._ttl = timedelta(hours=action_ttl_hours)

    async def store(
        self,
        *,
        session_id: uuid.UUID,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        proposal: Proposal,
        now: datetime,
    ) -> AssistantActionView:
        await self._sessions.lock(session_id=session_id)
        previous = await self._actions.get_pending_for_session(session_id=session_id)
        if previous is not None:
            # Conditional, so a card an apply claimed meanwhile stays applied.
            await self._actions.supersede(
                action_id=previous.id,
                status=(
                    AssistantActionStatus.EXPIRED
                    if self._is_expired(previous, now=now)
                    else AssistantActionStatus.CANCELLED
                ),
                now=now,
            )
        action = AssistantAction(
            session_id=session_id,
            message_id=message_id,
            user_id=user_id,
            kind=proposal.kind,
            payload=proposal.payload,
            card=dataclasses.asdict(proposal.card),
            status=AssistantActionStatus.PENDING,
            created_at=now,
            expires_at=now + self._ttl,
        )
        await self._actions.add(action=action)
        return self.view(action, now=now)

    async def get(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, action_id: uuid.UUID
    ) -> AssistantActionView:
        now = clock.now()
        action = await self._actions.get_for_user(
            action_id=action_id, session_id=session_id, user_id=user_id
        )
        if action is None:
            raise AssistantActionNotFoundError()
        return self.view(action, now=now)

    async def cancel(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, action_id: uuid.UUID
    ) -> AssistantActionView:
        now = clock.now()
        action = await self._actions.get_for_user(
            action_id=action_id, session_id=session_id, user_id=user_id, for_update=True
        )
        if action is None:
            raise AssistantActionNotFoundError()
        status = self.view(action, now=now).status
        if status is AssistantActionStatus.PENDING:
            action.status = AssistantActionStatus.CANCELLED
            action.resolved_at = now
            await self._actions.flush()
        elif status is not AssistantActionStatus.CANCELLED:
            raise AssistantActionNotPendingError()
        return self.view(action, now=now)

    async def views_for_messages(
        self, *, message_ids: Sequence[uuid.UUID], now: datetime
    ) -> dict[uuid.UUID, AssistantActionView]:
        actions = await self._actions.list_for_messages(message_ids=message_ids)
        return {action.message_id: self.view(action, now=now) for action in actions}

    @classmethod
    def view(cls, action: AssistantAction, *, now: datetime) -> AssistantActionView:
        status = action.status
        if status is AssistantActionStatus.PENDING and cls._is_expired(action, now=now):
            status = AssistantActionStatus.EXPIRED
        return AssistantActionView(
            id=action.id,
            kind=action.kind,
            status=status,
            card=action.card,
            created_at=action.created_at,
            expires_at=action.expires_at,
            result=action.result,
            error=action.error,
        )

    @staticmethod
    def _is_expired(action: AssistantAction, *, now: datetime) -> bool:
        return action.expires_at <= now

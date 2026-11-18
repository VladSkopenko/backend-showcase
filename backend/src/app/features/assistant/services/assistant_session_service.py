import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.assistant.dto import AssistantSessionView
from app.features.assistant.models import AssistantSession
from app.features.assistant.repositories import (
    AssistantMessageRepository,
    AssistantSessionRepository,
)
from app.features.assistant.services.exceptions import AssistantSessionNotFoundError


class AssistantSessionService:
    NEW_TITLE = "New chat"

    def __init__(self, session: AsyncSession) -> None:
        self._sessions = AssistantSessionRepository(session)
        self._messages = AssistantMessageRepository(session)

    async def create(self, *, user_id: uuid.UUID) -> AssistantSession:
        now = clock.now()
        chat_session = AssistantSession(
            user_id=user_id, title=self.NEW_TITLE, created_at=now, updated_at=now
        )
        await self._sessions.add(chat_session=chat_session)
        return chat_session

    async def list(self, *, user_id: uuid.UUID) -> Sequence[AssistantSession]:
        return await self._sessions.list_for_user(user_id=user_id)

    async def get(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> AssistantSessionView:
        chat_session = await self._sessions.get_for_user(session_id=session_id, user_id=user_id)
        if chat_session is None:
            raise AssistantSessionNotFoundError()
        return AssistantSessionView(
            id=chat_session.id,
            title=chat_session.title,
            created_at=chat_session.created_at,
            updated_at=chat_session.updated_at,
            messages=await self._messages.list_for_session(session_id=chat_session.id),
        )

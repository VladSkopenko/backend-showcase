import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.assistant.models import AssistantSession


class AssistantSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, chat_session: AssistantSession) -> None:
        self._session.add(chat_session)
        await self._session.flush()

    async def list_for_user(self, *, user_id: uuid.UUID) -> Sequence[AssistantSession]:
        sessions = await self._session.scalars(
            select(AssistantSession)
            .where(AssistantSession.user_id == user_id)
            .order_by(AssistantSession.updated_at.desc(), AssistantSession.id.desc())
        )
        return sessions.all()

    async def get_for_user(
        self, *, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> AssistantSession | None:
        chat_session: AssistantSession | None = await self._session.scalar(
            select(AssistantSession).where(
                AssistantSession.id == session_id, AssistantSession.user_id == user_id
            )
        )
        return chat_session

    async def touch(self, *, session_id: uuid.UUID, updated_at: datetime) -> None:
        await self._session.execute(
            update(AssistantSession)
            .where(AssistantSession.id == session_id)
            .values(updated_at=updated_at)
        )

    async def delete_inactive(self, *, updated_at_or_before: datetime) -> int:
        result = await self._session.execute(
            delete(AssistantSession)
            .where(AssistantSession.updated_at <= updated_at_or_before)
            .execution_options(synchronize_session=False)
        )
        return cast(CursorResult[Any], result).rowcount

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.assistant.enums import AssistantMessageRole
from app.features.assistant.models import AssistantMessage


class AssistantMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, message: AssistantMessage) -> None:
        self._session.add(message)
        await self._session.flush()

    async def list_for_session(self, *, session_id: uuid.UUID) -> Sequence[AssistantMessage]:
        messages = await self._session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.session_id == session_id)
            .order_by(AssistantMessage.created_at, AssistantMessage.id)
        )
        return messages.all()

    async def list_last_for_session(
        self, *, session_id: uuid.UUID, limit: int
    ) -> Sequence[AssistantMessage]:
        latest_first = await self._session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.session_id == session_id)
            .order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(latest_first.all()))

    async def list_latest_user_message_times_since(
        self, *, since: datetime, limit: int
    ) -> list[datetime]:
        latest_first = await self._session.scalars(
            select(AssistantMessage.created_at)
            .where(
                AssistantMessage.role == AssistantMessageRole.USER,
                AssistantMessage.created_at > since,
            )
            .order_by(AssistantMessage.created_at.desc())
            .limit(limit)
        )
        return list(latest_first)

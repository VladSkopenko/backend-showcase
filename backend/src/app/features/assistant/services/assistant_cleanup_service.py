from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.assistant.repositories import AssistantSessionRepository


class AssistantCleanupService:
    def __init__(self, session: AsyncSession, *, session_ttl_days: int) -> None:
        self._sessions = AssistantSessionRepository(session)
        self._session_ttl = timedelta(days=session_ttl_days)

    async def delete_inactive(self, *, now: datetime) -> int:
        return await self._sessions.delete_inactive(updated_at_or_before=now - self._session_ttl)

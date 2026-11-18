import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common import clock
from app.features.assistant.services.assistant_cleanup_service import AssistantCleanupService
from app.features.core.auth.services.auth_cleanup_service import AuthCleanupService

logger = logging.getLogger(__name__)


class CleanupJob:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], *, assistant_session_ttl_days: int
    ) -> None:
        self._sessionmaker = sessionmaker
        self._assistant_session_ttl_days = assistant_session_ttl_days

    async def run(self) -> None:
        async with self._sessionmaker() as session:
            try:
                deleted = await AuthCleanupService(session).delete_stale()
                assistant_sessions = await AssistantCleanupService(
                    session, session_ttl_days=self._assistant_session_ttl_days
                ).delete_inactive(now=clock.now())
            except BaseException:
                await session.rollback()
                raise
            await session.commit()
        if deleted.refresh_tokens or deleted.verification_codes or assistant_sessions:
            logger.info(
                "Deleted %d expired refresh tokens, %d old verification codes "
                "and %d inactive assistant sessions",
                deleted.refresh_tokens,
                deleted.verification_codes,
                assistant_sessions,
            )

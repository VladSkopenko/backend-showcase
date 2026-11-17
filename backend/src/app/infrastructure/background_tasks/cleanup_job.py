import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.core.auth.services.auth_cleanup_service import AuthCleanupService

logger = logging.getLogger(__name__)


class CleanupJob:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def run(self) -> None:
        async with self._sessionmaker() as session:
            try:
                deleted = await AuthCleanupService(session).delete_stale()
            except BaseException:
                await session.rollback()
                raise
            await session.commit()
        if deleted.refresh_tokens or deleted.verification_codes:
            logger.info(
                "Deleted %d expired refresh tokens and %d old verification codes",
                deleted.refresh_tokens,
                deleted.verification_codes,
            )

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.core.auth.dto import DeletedAuthRows
from app.features.core.auth.repositories import (
    RefreshTokenRepository,
    VerificationCodeRepository,
)
from app.features.core.auth.services.verification_code_service import VerificationCodeService


class AuthCleanupService:
    def __init__(self, session: AsyncSession) -> None:
        self._token_repository = RefreshTokenRepository(session)
        self._code_repository = VerificationCodeRepository(session)

    async def delete_stale(self) -> DeletedAuthRows:
        now = clock.now()
        # A rotated token stays until it expires, so presenting it again is still caught as reuse.
        refresh_tokens = await self._token_repository.delete_expired(now=now)
        # Codes inside the daily window still count toward the issue limits.
        verification_codes = await self._code_repository.delete_superseded(
            now=now, created_at_or_before=now - VerificationCodeService.DAILY_LIMIT_WINDOW
        )
        return DeletedAuthRows(refresh_tokens=refresh_tokens, verification_codes=verification_codes)

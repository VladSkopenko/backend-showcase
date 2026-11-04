import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.common.errors import DomainError
from app.config.settings import AuthSettings, Environment
from app.features.core.auth.dto import IssuedCode
from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.models import VerificationCode
from app.features.core.auth.repositories import VerificationCodeRepository
from app.features.core.auth.services.exceptions import (
    CodeExpiredError,
    CodeInvalidError,
    ResendTooSoonError,
)
from app.features.core.users.models import User

HOURLY_LIMIT_WINDOW = timedelta(hours=1)


class VerificationCodeService:
    def __init__(self, session: AsyncSession, auth: AuthSettings, environment: Environment) -> None:
        self._code_repository = VerificationCodeRepository(session)
        self._auth = auth
        self._environment = environment

    def generate(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    async def issue(self, *, user: User, purpose: VerificationPurpose) -> IssuedCode:
        now = clock.now()
        await self._ensure_issue_allowed(user=user, purpose=purpose, now=now)
        plain_code = self.generate()
        await self._code_repository.add(
            code=VerificationCode(
                user_id=user.id,
                purpose=purpose,
                code_hash=self._hash_code(plain_code),
                created_at=now,
                expires_at=now + timedelta(minutes=self._auth.verification_code_ttl_minutes),
            )
        )
        # Deployed environments are reachable from the internet, so only `local` echoes the code.
        debug_code = plain_code if self._environment == "local" else None
        return IssuedCode(user=user, plain_code=plain_code, debug_code=debug_code)

    async def consume(
        self, *, user: User, purpose: VerificationPurpose, code: str
    ) -> DomainError | None:
        current = await self._code_repository.get_latest(user_id=user.id, purpose=purpose)
        now = clock.now()
        if (
            current is None
            or current.consumed_at is not None
            or current.attempts >= self._auth.max_code_attempts
        ):
            return CodeInvalidError()
        if current.expires_at <= now:
            return CodeExpiredError()
        if not self._matches(code, current.code_hash):
            await self._code_repository.increment_attempts(code_id=current.id)
            return CodeInvalidError()
        current.consumed_at = now
        return None

    def _hash_code(self, code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    def _matches(self, code: str, code_hash: str) -> bool:
        return hmac.compare_digest(self._hash_code(code), code_hash)

    async def _ensure_issue_allowed(
        self, *, user: User, purpose: VerificationPurpose, now: datetime
    ) -> None:
        earliest_allowed = [now]
        latest = await self._code_repository.get_latest(user_id=user.id, purpose=purpose)
        if latest is not None:
            earliest_allowed.append(
                latest.created_at + timedelta(seconds=self._auth.resend_cooldown_seconds)
            )
        recent = await self._code_repository.list_creation_times_since(
            user_id=user.id, purpose=purpose, since=now - HOURLY_LIMIT_WINDOW
        )
        if len(recent) >= self._auth.max_codes_per_hour:
            earliest_allowed.append(recent[-self._auth.max_codes_per_hour] + HOURLY_LIMIT_WINDOW)
        wait = max(earliest_allowed) - now
        if wait > timedelta(0):
            raise ResendTooSoonError(retry_after=math.ceil(wait.total_seconds()))

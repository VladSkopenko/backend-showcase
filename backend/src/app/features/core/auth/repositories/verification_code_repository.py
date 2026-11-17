import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.models import VerificationCode


class VerificationCodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, code: VerificationCode) -> None:
        self._session.add(code)
        await self._session.flush()

    async def get_latest(
        self, *, user_id: uuid.UUID, purpose: VerificationPurpose
    ) -> VerificationCode | None:
        code: VerificationCode | None = await self._session.scalar(
            select(VerificationCode)
            .where(VerificationCode.user_id == user_id, VerificationCode.purpose == purpose)
            .order_by(VerificationCode.created_at.desc())
            .limit(1)
        )
        return code

    async def list_creation_times_since(
        self, *, user_id: uuid.UUID, purpose: VerificationPurpose, since: datetime
    ) -> list[datetime]:
        creation_times = await self._session.scalars(
            select(VerificationCode.created_at)
            .where(
                VerificationCode.user_id == user_id,
                VerificationCode.purpose == purpose,
                VerificationCode.created_at > since,
            )
            .order_by(VerificationCode.created_at)
        )
        return list(creation_times)

    async def increment_attempts(self, *, code_id: uuid.UUID) -> None:
        # Incremented in SQL, not in Python, so concurrent wrong guesses never overwrite each other.
        await self._session.execute(
            update(VerificationCode)
            .where(VerificationCode.id == code_id)
            .values(attempts=VerificationCode.attempts + 1)
        )

    async def delete_superseded(self, *, now: datetime, created_at_or_before: datetime) -> int:
        # The newest code of a user and purpose always stays: verify reads only that one.
        newer = aliased(VerificationCode)
        result = await self._session.execute(
            delete(VerificationCode)
            .where(
                VerificationCode.expires_at <= now,
                VerificationCode.created_at <= created_at_or_before,
                exists().where(
                    newer.user_id == VerificationCode.user_id,
                    newer.purpose == VerificationCode.purpose,
                    newer.created_at > VerificationCode.created_at,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        return cast(CursorResult[Any], result).rowcount

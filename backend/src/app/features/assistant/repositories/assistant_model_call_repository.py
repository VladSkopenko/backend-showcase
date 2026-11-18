from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.assistant.models import AssistantModelCall


class AssistantModelCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, call: AssistantModelCall) -> None:
        self._session.add(call)
        await self._session.flush()

    async def lock_for_transaction(self, *, key: int) -> None:
        await self._session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    async def sum_cost_since(self, *, since: datetime) -> int:
        total = await self._session.scalar(
            select(func.coalesce(func.sum(AssistantModelCall.cost_micro_usd), 0)).where(
                AssistantModelCall.created_at >= since
            )
        )
        return int(total or 0)

import asyncio

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.features.core.health.dto import HealthReport
from app.features.core.health.repositories import DatabaseProbeRepository


class HealthService:
    def __init__(self, engine: AsyncEngine, *, timeout_seconds: float) -> None:
        self._probe_repository = DatabaseProbeRepository(engine)
        self._timeout_seconds = timeout_seconds

    async def check(self) -> HealthReport:
        # asyncio.timeout, not anyio.fail_after: anyio's cancel scope also cancels SQLAlchemy's
        # shielded connection close and logs an ERROR for every timed-out probe.
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await self._probe_repository.ping()
        except TimeoutError, SQLAlchemyError, OSError:
            return HealthReport(database_ok=False)
        return HealthReport(database_ok=True)

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

logger = logging.getLogger(__name__)


class PeriodicTask:
    def __init__(
        self, *, name: str, interval_seconds: float, job: Callable[[], Awaitable[None]]
    ) -> None:
        self._name = name
        self._interval_seconds = interval_seconds
        self._job = job
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name=self._name)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._job()
            except Exception:
                logger.exception("Background task %r failed; the next run tries again", self._name)
            await asyncio.sleep(self._interval_seconds)

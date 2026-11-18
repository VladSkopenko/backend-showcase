import asyncio
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from decimal import Decimal
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.messages.ai import UsageMetadata
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.assistant.dto import ModelPrices
from app.features.assistant.services.exceptions import (
    AssistantProviderError,
    AssistantTurnTimeoutError,
)
from app.features.assistant.services.usage_ledger import UsageLedger


class ModelCallRunner:
    """What a turn and an apply comment share: the wall-clock cap, the provider error mapping,
    the usage ledger and short transactions."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        model_name: str,
        prices: ModelPrices,
        timezone: ZoneInfo,
        daily_budget_usd: Decimal,
        turns_per_minute: int,
        turn_timeout_seconds: int,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._model_name = model_name
        self._prices = prices
        self._timezone = timezone
        self._daily_budget_usd = daily_budget_usd
        self._turns_per_minute = turns_per_minute
        self.turn_timeout_seconds = turn_timeout_seconds
        self._deadline = 0.0

    def start_clock(self) -> None:
        self._deadline = asyncio.get_running_loop().time() + self.turn_timeout_seconds

    async def before_deadline[T](self, awaitable: Awaitable[T]) -> T:
        timeout = asyncio.timeout_at(self._deadline)
        try:
            async with timeout:
                return await awaitable
        except TimeoutError:
            if timeout.expired():
                raise AssistantTurnTimeoutError() from None
            raise

    async def next_chunk(self, chunks: AsyncIterator[AIMessage]) -> AIMessageChunk | None:
        try:
            chunk = await self.before_deadline(anext(chunks, None))
        except AssistantTurnTimeoutError:
            raise
        except Exception as error:
            raise AssistantProviderError() from error
        if chunk is None or isinstance(chunk, AIMessageChunk):
            return chunk
        return AIMessageChunk(
            content=chunk.content,
            tool_calls=chunk.tool_calls,
            invalid_tool_calls=chunk.invalid_tool_calls,
            usage_metadata=chunk.usage_metadata,
        )

    async def record(self, usage: UsageMetadata) -> None:
        async with self.transaction() as session:
            await self.ledger(session).record(usage=usage, model=self._model_name)

    def ledger(self, session: AsyncSession) -> UsageLedger:
        return UsageLedger(
            session,
            prices=self._prices,
            timezone=self._timezone,
            daily_budget_usd=self._daily_budget_usd,
            turns_per_minute=self._turns_per_minute,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self._sessionmaker() as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise
            await session.commit()

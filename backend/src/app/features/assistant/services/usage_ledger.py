import logging
import math
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from langchain_core.messages.ai import UsageMetadata
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.assistant.dto import ModelPrices
from app.features.assistant.models import AssistantModelCall
from app.features.assistant.repositories import (
    AssistantMessageRepository,
    AssistantModelCallRepository,
)
from app.features.assistant.services.exceptions import (
    AssistantBudgetExhaustedError,
    AssistantBusyError,
)

logger = logging.getLogger(__name__)


class UsageLedger:
    """Records what every model call cost and refuses a new turn past the global limits.

    The limits are soft: a turn checks them before it starts and reserves nothing, so the turns
    already running finish even when they take the spend past the budget.
    """

    # One key for the whole system: the check and the caller's insert of the user message run
    # under it until the caller's transaction ends, so parallel turns cannot all pass the cap.
    LIMITS_LOCK_KEY = 4_300_000_001
    TURNS_WINDOW = timedelta(minutes=1)
    MICRO_USD_PER_USD = 1_000_000

    def __init__(
        self,
        session: AsyncSession,
        *,
        prices: ModelPrices,
        timezone: ZoneInfo,
        daily_budget_usd: Decimal,
        turns_per_minute: int,
    ) -> None:
        self._calls = AssistantModelCallRepository(session)
        self._messages = AssistantMessageRepository(session)
        self._prices = prices
        self._timezone = timezone
        self._daily_budget_micro_usd = daily_budget_usd * self.MICRO_USD_PER_USD
        self._turns_per_minute = turns_per_minute

    async def check(self, *, now: datetime) -> None:
        await self._calls.lock_for_transaction(key=self.LIMITS_LOCK_KEY)
        local_day = now.astimezone(self._timezone).date()
        spent_micro_usd = await self._spent_today(now=now)
        if spent_micro_usd >= self._daily_budget_micro_usd:
            logger.warning(
                "The assistant's daily budget is exhausted: spent %d micro-USD of %s",
                spent_micro_usd,
                self._daily_budget_micro_usd,
            )
            next_midnight = datetime.combine(
                local_day + timedelta(days=1), time(), tzinfo=self._timezone
            )
            raise AssistantBudgetExhaustedError(retry_after=self._seconds(next_midnight - now))
        recent = await self._messages.list_latest_user_message_times_since(
            since=now - self.TURNS_WINDOW, limit=self._turns_per_minute
        )
        if len(recent) >= self._turns_per_minute:
            oldest_counted = recent[-1]
            raise AssistantBusyError(
                retry_after=self._seconds(oldest_counted + self.TURNS_WINDOW - now)
            )

    async def is_budget_exhausted(self, *, now: datetime) -> bool:
        return await self._spent_today(now=now) >= self._daily_budget_micro_usd

    async def _spent_today(self, *, now: datetime) -> int:
        local_day = now.astimezone(self._timezone).date()
        midnight = datetime.combine(local_day, time(), tzinfo=self._timezone)
        return await self._calls.sum_cost_since(since=midnight)

    async def record(self, *, usage: UsageMetadata, model: str) -> None:
        input_tokens = usage["input_tokens"]
        cached_input_tokens = usage.get("input_token_details", {}).get("cache_read", 0)
        output_tokens = usage["output_tokens"]
        # A price per million tokens is the price of one token in micro-dollars.
        cost = (
            (input_tokens - cached_input_tokens) * self._prices.input_per_million_usd
            + cached_input_tokens * self._prices.cached_input_per_million_usd
            + output_tokens * self._prices.output_per_million_usd
        )
        await self._calls.add(
            call=AssistantModelCall(
                model=model,
                input_tokens=input_tokens,
                cached_input_tokens=cached_input_tokens,
                output_tokens=output_tokens,
                cost_micro_usd=round(cost),
                created_at=clock.now(),
            )
        )

    @staticmethod
    def _seconds(wait: timedelta) -> int:
        return math.ceil(wait.total_seconds())

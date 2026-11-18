import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    InvalidToolCall,
    SystemMessage,
    ToolCall,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common import clock
from app.common.ai_tools import AiToolErrors, cut_tool_result, tool_error
from app.common.errors import DomainError
from app.features.assistant.dto import AssistantEvent, ModelPrices
from app.features.assistant.enums import AssistantMessageRole
from app.features.assistant.models import AssistantMessage
from app.features.assistant.repositories import (
    AssistantMessageRepository,
    AssistantSessionRepository,
)
from app.features.assistant.services.assistant_session_service import AssistantSessionService
from app.features.assistant.services.exceptions import (
    AssistantProviderError,
    AssistantSessionNotFoundError,
    AssistantTurnTimeoutError,
)
from app.features.assistant.services.system_prompt_builder import SystemPromptBuilder
from app.features.assistant.services.usage_ledger import UsageLedger

logger = logging.getLogger(__name__)


class AssistantTurnService:
    """One turn: `start()` stores the question in a short transaction, `stream()` answers it.

    No transaction is open during a model call: tools open their own per call, the usage of
    every call is recorded in its own, and the answer is stored in one more at the end.
    """

    TIMEOUT_CODE = "ASSISTANT_TIMEOUT"
    TIMEOUT_MESSAGE = "The assistant took too long to answer."
    PROVIDER_ERROR_CODE = "ASSISTANT_PROVIDER_ERROR"
    PROVIDER_ERROR_MESSAGE = "The assistant could not reach its model."
    SERVER_ERROR_CODE = "SERVER_ERROR"
    SERVER_ERROR_MESSAGE = "Something went wrong."
    FALLBACK_TEXT = "I could not finish working on that. Please ask again, maybe in smaller steps."
    TITLE_MAX_CHARS = 60

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        model: BaseChatModel,
        model_name: str,
        prices: ModelPrices,
        tools: Sequence[BaseTool],
        prompts: SystemPromptBuilder,
        user_id: uuid.UUID,
        first_name: str,
        history_messages: int,
        max_rounds: int,
        max_tool_calls: int,
        turn_timeout_seconds: int,
        tool_result_max_chars: int,
        timezone: ZoneInfo,
        daily_budget_usd: Decimal,
        turns_per_minute: int,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._model = model.bind_tools(tools)
        self._model_name = model_name
        self._prices = prices
        self._tools = {tool.name: tool for tool in tools}
        self._prompts = prompts
        self._user_id = user_id
        self._first_name = first_name
        self._history_messages = history_messages
        self._max_rounds = max_rounds
        self._max_tool_calls = max_tool_calls
        self._turn_timeout_seconds = turn_timeout_seconds
        self._tool_result_max_chars = tool_result_max_chars
        self._timezone = timezone
        self._daily_budget_usd = daily_budget_usd
        self._turns_per_minute = turns_per_minute
        self._session_id: uuid.UUID | None = None
        self._messages: list[BaseMessage] = []
        self._deadline = 0.0

    async def start(self, *, session_id: uuid.UUID, text: str) -> None:
        now = clock.now()
        async with self._transaction() as session:
            chat_session = await AssistantSessionRepository(session).get_for_user(
                session_id=session_id, user_id=self._user_id
            )
            if chat_session is None:
                raise AssistantSessionNotFoundError()
            await self._ledger(session).check(now=now)
            messages = AssistantMessageRepository(session)
            await messages.add(
                message=AssistantMessage(
                    session_id=session_id,
                    role=AssistantMessageRole.USER,
                    text=text,
                    created_at=now,
                )
            )
            if chat_session.title == AssistantSessionService.NEW_TITLE:
                chat_session.title = text[: self.TITLE_MAX_CHARS]
            chat_session.updated_at = now
            history = await messages.list_last_for_session(
                session_id=session_id, limit=self._history_messages
            )
        self._session_id = session_id
        self._messages = [
            SystemMessage(self._prompts.build(first_name=self._first_name)),
            *(self._to_model_message(message) for message in history),
        ]

    async def stream(self) -> AsyncIterator[AssistantEvent]:
        self._deadline = asyncio.get_running_loop().time() + self._turn_timeout_seconds
        try:
            async for event in self._run():
                yield event
        except AssistantTurnTimeoutError:
            logger.warning(
                "The assistant turn in session %s timed out after %d s",
                self._session_id,
                self._turn_timeout_seconds,
            )
            yield AssistantEvent.error(code=self.TIMEOUT_CODE, message=self.TIMEOUT_MESSAGE)
        except AssistantProviderError:
            logger.exception("The model provider failed in assistant session %s", self._session_id)
            yield AssistantEvent.error(
                code=self.PROVIDER_ERROR_CODE, message=self.PROVIDER_ERROR_MESSAGE
            )
        except Exception:
            logger.exception("The assistant turn in session %s failed", self._session_id)
            yield AssistantEvent.error(
                code=self.SERVER_ERROR_CODE, message=self.SERVER_ERROR_MESSAGE
            )

    async def _run(self) -> AsyncIterator[AssistantEvent]:
        # Everything sent as a chunk is what gets saved, so the read-back matches what was seen.
        sent: list[str] = []
        calls_made = 0
        answered = False
        for round_number in range(1, self._max_rounds + 1):
            yield AssistantEvent.thinking()
            reply = AIMessageChunk(content="")
            chunks = self._model.astream(self._messages)
            while (chunk := await self._next_chunk(chunks)) is not None:
                reply = reply + chunk
                if chunk.text:
                    sent.append(str(chunk.text))
                    yield AssistantEvent.chunk(str(chunk.text))
            if reply.usage_metadata is not None:
                await self._record(reply.usage_metadata)
            if not reply.tool_calls and not reply.invalid_tool_calls:
                answered = True
                break
            self._messages.append(message_chunk_to_message(reply))
            last_round = round_number == self._max_rounds
            if last_round or calls_made + len(reply.tool_calls) > self._max_tool_calls:
                break
            for invalid_call in reply.invalid_tool_calls:
                self._messages.append(self._refuse_malformed_call(invalid_call))
            for call in reply.tool_calls:
                self._messages.append(await self._run_tool(call))
            calls_made += len(reply.tool_calls)
        if not answered or not "".join(sent):
            sent.append(self.FALLBACK_TEXT)
            yield AssistantEvent.chunk(self.FALLBACK_TEXT)
        yield await self._finish("".join(sent))

    async def _next_chunk(self, chunks: AsyncIterator[AIMessage]) -> AIMessageChunk | None:
        try:
            chunk = await self._before_deadline(anext(chunks, None))
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

    async def _run_tool(self, call: ToolCall) -> ToolMessage:
        call_id = call["id"] or ""
        try:
            result = await self._before_deadline(self._tools[call["name"]].ainvoke(call))
        except AssistantTurnTimeoutError:
            raise
        except DomainError as error:
            return self._tool_message(call_id, tool_error(error.code, error.message))
        except Exception:
            logger.exception(
                "Tool %s failed in assistant session %s", call["name"], self._session_id
            )
            return self._tool_message(call_id, tool_error(AiToolErrors.TOOL_FAILED))
        return self._tool_message(
            call_id,
            cut_tool_result(str(result.content), max_chars=self._tool_result_max_chars),
            status=result.status,
        )

    def _refuse_malformed_call(self, call: InvalidToolCall) -> ToolMessage:
        return self._tool_message(
            call["id"] or "",
            tool_error(AiToolErrors.MALFORMED_CALL, "The arguments are not a JSON object."),
        )

    async def _before_deadline[T](self, awaitable: Awaitable[T]) -> T:
        timeout = asyncio.timeout_at(self._deadline)
        try:
            async with timeout:
                return await awaitable
        except TimeoutError:
            if timeout.expired():
                raise AssistantTurnTimeoutError() from None
            raise

    async def _record(self, usage: UsageMetadata) -> None:
        async with self._transaction() as session:
            await self._ledger(session).record(usage=usage, model=self._model_name)

    def _ledger(self, session: AsyncSession) -> UsageLedger:
        return UsageLedger(
            session,
            prices=self._prices,
            timezone=self._timezone,
            daily_budget_usd=self._daily_budget_usd,
            turns_per_minute=self._turns_per_minute,
        )

    async def _finish(self, text: str) -> AssistantEvent:
        if self._session_id is None:
            raise RuntimeError("stream() needs start() first")
        now = clock.now()
        message = AssistantMessage(
            session_id=self._session_id,
            role=AssistantMessageRole.ASSISTANT,
            text=text,
            created_at=now,
        )
        async with self._transaction() as session:
            await AssistantMessageRepository(session).add(message=message)
            await AssistantSessionRepository(session).touch(
                session_id=self._session_id, updated_at=now
            )
        return AssistantEvent.done(message_id=message.id, created_at=message.created_at)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        async with self._sessionmaker() as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise
            await session.commit()

    @staticmethod
    def _to_model_message(message: AssistantMessage) -> BaseMessage:
        if message.role is AssistantMessageRole.USER:
            return HumanMessage(message.text)
        return AIMessage(message.text)

    @staticmethod
    def _tool_message(
        call_id: str, content: str, status: Literal["success", "error"] = "error"
    ) -> ToolMessage:
        return ToolMessage(content=content, tool_call_id=call_id, status=status)

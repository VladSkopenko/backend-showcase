import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage, SystemMessage

from app.common import clock
from app.common.ai_tools import ActionApplier
from app.features.assistant.dto import ApplyOutcome, AssistantActionView, AssistantEvent
from app.features.assistant.enums import AssistantActionStatus, AssistantMessageRole
from app.features.assistant.models import AssistantMessage
from app.features.assistant.repositories import (
    AssistantMessageRepository,
    AssistantSessionRepository,
)
from app.features.assistant.services.action_apply_executor import ActionApplyExecutor
from app.features.assistant.services.assistant_turn_service import AssistantTurnService
from app.features.assistant.services.exceptions import (
    AssistantProviderError,
    AssistantTurnTimeoutError,
)
from app.features.assistant.services.model_call_runner import ModelCallRunner
from app.features.assistant.services.model_history_builder import ModelHistoryBuilder
from app.features.assistant.services.system_prompt_builder import SystemPromptBuilder

logger = logging.getLogger(__name__)


class AssistantApplyService:
    APPLIED_TEXT = "Done."
    FAILED_TEXT = "That did not work: {message}"

    def __init__(
        self,
        runner: ModelCallRunner,
        *,
        model: BaseChatModel,
        appliers: Mapping[str, ActionApplier],
        prompts: SystemPromptBuilder,
        user_id: uuid.UUID,
        first_name: str,
        history_messages: int,
        action_ttl_hours: int,
    ) -> None:
        self._runner = runner
        self._model = model
        self._appliers = appliers
        self._prompts = prompts
        self._user_id = user_id
        self._first_name = first_name
        self._history_messages = history_messages
        self._action_ttl_hours = action_ttl_hours
        self._session_id: uuid.UUID | None = None
        self._outcome: ApplyOutcome | None = None
        self._budget_exhausted = False
        self._messages: list[BaseMessage] = []

    async def start(self, *, session_id: uuid.UUID, action_id: uuid.UUID) -> None:
        now = clock.now()
        async with self._runner.transaction() as session:
            outcome = await ActionApplyExecutor(session, appliers=self._appliers).apply(
                user_id=self._user_id, session_id=session_id, action_id=action_id, now=now
            )
        self._session_id = session_id
        self._outcome = outcome
        if outcome.replayed:
            return
        async with self._runner.transaction() as session:
            self._budget_exhausted = await self._runner.ledger(session).is_budget_exhausted(now=now)
            history = await ModelHistoryBuilder(
                session, action_ttl_hours=self._action_ttl_hours
            ).build(session_id=session_id, limit=self._history_messages, now=now)
        self._messages = [
            SystemMessage(self._prompts.build(first_name=self._first_name)),
            *history,
            HumanMessage(self._note(outcome.action)),
        ]

    async def stream(self) -> AsyncIterator[AssistantEvent]:
        if self._outcome is None:
            raise RuntimeError("stream() needs start() first")
        yield AssistantEvent.action(self._outcome.action)
        if self._outcome.replayed:
            yield AssistantEvent.done(message_id=None, created_at=None)
            return
        self._runner.start_clock()
        try:
            async for event in self._comment(self._outcome.action):
                yield event
        except AssistantTurnTimeoutError:
            logger.warning(
                "The comment on an applied card in session %s timed out", self._session_id
            )
            yield AssistantEvent.error(
                code=AssistantTurnService.TIMEOUT_CODE,
                message=AssistantTurnService.TIMEOUT_MESSAGE,
            )
        except AssistantProviderError:
            logger.exception("The model provider failed in assistant session %s", self._session_id)
            yield AssistantEvent.error(
                code=AssistantTurnService.PROVIDER_ERROR_CODE,
                message=AssistantTurnService.PROVIDER_ERROR_MESSAGE,
            )
        except Exception:
            logger.exception(
                "The comment on an applied card in session %s failed", self._session_id
            )
            yield AssistantEvent.error(
                code=AssistantTurnService.SERVER_ERROR_CODE,
                message=AssistantTurnService.SERVER_ERROR_MESSAGE,
            )

    async def _comment(self, action: AssistantActionView) -> AsyncIterator[AssistantEvent]:
        yield AssistantEvent.thinking()
        if self._budget_exhausted:
            text = self._fixed_text(action)
            yield AssistantEvent.chunk(text)
            yield await self._finish(text)
            return
        sent: list[str] = []
        reply = AIMessageChunk(content="")
        chunks = self._model.astream(self._messages)
        while (chunk := await self._runner.next_chunk(chunks)) is not None:
            reply = reply + chunk
            if chunk.text:
                sent.append(str(chunk.text))
                yield AssistantEvent.chunk(str(chunk.text))
        if reply.usage_metadata is not None:
            await self._runner.record(reply.usage_metadata)
        if not "".join(sent):
            text = self._fixed_text(action)
            sent.append(text)
            yield AssistantEvent.chunk(text)
        yield await self._finish("".join(sent))

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
        async with self._runner.transaction() as session:
            await AssistantMessageRepository(session).add(message=message)
            await AssistantSessionRepository(session).touch(
                session_id=self._session_id, updated_at=now
            )
        return AssistantEvent.done(message_id=message.id, created_at=message.created_at)

    def _fixed_text(self, action: AssistantActionView) -> str:
        if action.status is AssistantActionStatus.APPLIED or action.error is None:
            return self.APPLIED_TEXT
        return self.FAILED_TEXT.format(message=action.error["message"])

    @staticmethod
    def _note(action: AssistantActionView) -> str:
        details = action.result if action.status is AssistantActionStatus.APPLIED else action.error
        return (
            f"The guest pressed {action.card['confirm_label']} on the card "
            f"'{action.card['title']}'. Outcome: {action.status.value}, {json.dumps(details)}. "
            "Comment on it briefly in the guest's language."
        )

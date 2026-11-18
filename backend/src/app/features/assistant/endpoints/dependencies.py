from typing import Annotated

from fastapi import Depends, Request
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import database
from app.common.ai_tools import AiToolContext, ProposalSink
from app.common.database import get_session
from app.config.settings import OpenAISettings, Settings, get_settings
from app.features.assistant.dto import ModelPrices
from app.features.assistant.services.assistant_action_service import AssistantActionService
from app.features.assistant.services.assistant_apply_service import AssistantApplyService
from app.features.assistant.services.assistant_session_service import AssistantSessionService
from app.features.assistant.services.assistant_turn_service import AssistantTurnService
from app.features.assistant.services.exceptions import AssistantUnavailableError
from app.features.assistant.services.model_call_runner import ModelCallRunner
from app.features.assistant.services.system_prompt_builder import SystemPromptBuilder
from app.features.assistant.services.toolkit_builder import ToolkitBuilder
from app.features.core.auth.endpoints.dependencies import CurrentUserDep
from app.features.core.auth.schemas import UserResponse
from app.features.core.auth.services.exceptions import EmailNotVerifiedError

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def require_assistant_configured(settings: SettingsDep) -> None:
    if not settings.openai.is_configured:
        raise AssistantUnavailableError()


def get_verified_user(user: CurrentUserDep) -> UserResponse:
    if user.email_verified_at is None:
        raise EmailNotVerifiedError()
    return user


def get_assistant_session_service(
    session: SessionDep, settings: SettingsDep
) -> AssistantSessionService:
    return AssistantSessionService(session, action_ttl_hours=settings.assistant.action_ttl_hours)


def get_assistant_action_service(
    session: SessionDep, settings: SettingsDep
) -> AssistantActionService:
    return AssistantActionService(session, action_ttl_hours=settings.assistant.action_ttl_hours)


def get_model_call_runner(settings: SettingsDep) -> ModelCallRunner:
    # The turn and the apply open their own short transactions, so they take the sessionmaker.
    return ModelCallRunner(
        database.get_sessionmaker(),
        model_name=settings.openai.model,
        prices=ModelPrices(
            input_per_million_usd=settings.openai.input_price_per_million_usd,
            cached_input_per_million_usd=settings.openai.cached_input_price_per_million_usd,
            output_per_million_usd=settings.openai.output_price_per_million_usd,
        ),
        timezone=settings.booking.timezone,
        daily_budget_usd=settings.assistant.daily_budget_usd,
        turns_per_minute=settings.assistant.turns_per_minute,
        turn_timeout_seconds=settings.assistant.turn_timeout_seconds,
    )


def build_chat_model(openai: OpenAISettings) -> ChatOpenAI | None:
    # Built once per process; langchain-openai shares one cached httpx pool across instances.
    if not openai.is_configured:
        return None
    return ChatOpenAI(
        model=openai.model,
        api_key=openai.api_key,
        max_completion_tokens=openai.max_output_tokens,
        timeout=openai.request_timeout_seconds,
        max_retries=1,
        stream_usage=True,
        use_responses_api=False,
    )


def get_chat_model(request: Request) -> BaseChatModel:
    model: ChatOpenAI | None = request.app.state.chat_model
    if model is None:
        raise AssistantUnavailableError()
    return model


VerifiedUserDep = Annotated[UserResponse, Depends(get_verified_user)]
AssistantSessionServiceDep = Annotated[
    AssistantSessionService, Depends(get_assistant_session_service)
]
ChatModelDep = Annotated[BaseChatModel, Depends(get_chat_model)]
AssistantActionServiceDep = Annotated[AssistantActionService, Depends(get_assistant_action_service)]
ModelCallRunnerDep = Annotated[ModelCallRunner, Depends(get_model_call_runner)]


def get_tool_context(user: VerifiedUserDep, settings: SettingsDep) -> AiToolContext:
    return AiToolContext(
        user_id=user.id,
        sessionmaker=database.get_sessionmaker(),
        public_base_url=settings.media.public_base_url,
        booking=settings.booking,
        max_item_quantity=settings.preorder.max_item_quantity,
        proposals=ProposalSink(),
    )


ToolContextDep = Annotated[AiToolContext, Depends(get_tool_context)]


def get_assistant_turn_service(
    user: VerifiedUserDep,
    model: ChatModelDep,
    runner: ModelCallRunnerDep,
    context: ToolContextDep,
    settings: SettingsDep,
) -> AssistantTurnService:
    return AssistantTurnService(
        runner,
        model=model,
        tools=ToolkitBuilder(context).build(),
        proposals=context.proposals,
        prompts=SystemPromptBuilder(booking=settings.booking),
        user_id=user.id,
        first_name=user.first_name,
        history_messages=settings.assistant.history_messages,
        max_rounds=settings.assistant.max_rounds,
        max_tool_calls=settings.assistant.max_tool_calls,
        tool_result_max_chars=settings.assistant.tool_result_max_chars,
        action_ttl_hours=settings.assistant.action_ttl_hours,
    )


def get_assistant_apply_service(
    user: VerifiedUserDep,
    model: ChatModelDep,
    runner: ModelCallRunnerDep,
    context: ToolContextDep,
    settings: SettingsDep,
) -> AssistantApplyService:
    return AssistantApplyService(
        runner,
        model=model,
        appliers=ToolkitBuilder(context).appliers(),
        prompts=SystemPromptBuilder(booking=settings.booking),
        user_id=user.id,
        first_name=user.first_name,
        history_messages=settings.assistant.history_messages,
        action_ttl_hours=settings.assistant.action_ttl_hours,
    )


AssistantTurnServiceDep = Annotated[AssistantTurnService, Depends(get_assistant_turn_service)]
AssistantApplyServiceDep = Annotated[AssistantApplyService, Depends(get_assistant_apply_service)]

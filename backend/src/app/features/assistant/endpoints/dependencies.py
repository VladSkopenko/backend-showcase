from typing import Annotated

from fastapi import Depends
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import database
from app.common.ai_tools import AiToolContext
from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.assistant.dto import ModelPrices
from app.features.assistant.services.assistant_session_service import AssistantSessionService
from app.features.assistant.services.assistant_turn_service import AssistantTurnService
from app.features.assistant.services.exceptions import AssistantUnavailableError
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


def get_assistant_session_service(session: SessionDep) -> AssistantSessionService:
    return AssistantSessionService(session)


def get_chat_model(settings: SettingsDep) -> BaseChatModel:
    return ChatOpenAI(
        model=settings.openai.model,
        api_key=settings.openai.api_key,
        max_completion_tokens=settings.openai.max_output_tokens,
        timeout=settings.openai.request_timeout_seconds,
        max_retries=1,
        stream_usage=True,
        use_responses_api=False,
    )


VerifiedUserDep = Annotated[UserResponse, Depends(get_verified_user)]
AssistantSessionServiceDep = Annotated[
    AssistantSessionService, Depends(get_assistant_session_service)
]
ChatModelDep = Annotated[BaseChatModel, Depends(get_chat_model)]


def get_assistant_turn_service(
    user: VerifiedUserDep, model: ChatModelDep, settings: SettingsDep
) -> AssistantTurnService:
    # The turn opens its own short transactions, so it takes the sessionmaker, not a session.
    context = AiToolContext(
        user_id=user.id,
        sessionmaker=database.get_sessionmaker(),
        public_base_url=settings.media.public_base_url,
        booking=settings.booking,
        max_item_quantity=settings.preorder.max_item_quantity,
    )
    return AssistantTurnService(
        context.sessionmaker,
        model=model,
        model_name=settings.openai.model,
        prices=ModelPrices(
            input_per_million_usd=settings.openai.input_price_per_million_usd,
            cached_input_per_million_usd=settings.openai.cached_input_price_per_million_usd,
            output_per_million_usd=settings.openai.output_price_per_million_usd,
        ),
        tools=ToolkitBuilder(context).build(),
        prompts=SystemPromptBuilder(booking=settings.booking),
        user_id=user.id,
        first_name=user.first_name,
        history_messages=settings.assistant.history_messages,
        max_rounds=settings.assistant.max_rounds,
        max_tool_calls=settings.assistant.max_tool_calls,
        turn_timeout_seconds=settings.assistant.turn_timeout_seconds,
        tool_result_max_chars=settings.assistant.tool_result_max_chars,
        timezone=settings.booking.timezone,
        daily_budget_usd=settings.assistant.daily_budget_usd,
        turns_per_minute=settings.assistant.turns_per_minute,
    )


AssistantTurnServiceDep = Annotated[AssistantTurnService, Depends(get_assistant_turn_service)]

import uuid

from fastapi import APIRouter, Depends, status

from app.common.error_responses import error_responses
from app.features.assistant.endpoints.dependencies import (
    AssistantSessionServiceDep,
    AssistantTurnServiceDep,
    VerifiedUserDep,
    require_assistant_configured,
)
from app.features.assistant.endpoints.errors import DOCUMENTED_ERROR_STATUSES
from app.features.assistant.endpoints.event_stream import EventStreamResponse
from app.features.assistant.endpoints.openapi_tags import AssistantOpenApiTags
from app.features.assistant.schemas import (
    AssistantMessageRequest,
    AssistantSessionDetailResponse,
    AssistantSessionResponse,
)
from app.features.assistant.services.exceptions import (
    AssistantSessionNotFoundError,
    AssistantUnavailableError,
)
from app.features.core.auth.services.exceptions import (
    EmailNotVerifiedError,
    NotAuthenticatedError,
)

router = APIRouter(
    prefix="/assistant",
    tags=[AssistantOpenApiTags.ASSISTANT],
    dependencies=[Depends(require_assistant_configured)],
)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=AssistantSessionResponse,
    responses=error_responses(
        NotAuthenticatedError,
        EmailNotVerifiedError,
        AssistantUnavailableError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Starts a new chat session for the signed-in user and answers it with its id, title and "
        "timestamps. The title is a placeholder until the first message sets it. A user whose "
        "email is not "
        "verified is refused; the `guest_token` cookie alone does not sign anyone in. "
        "Unavailable when the model provider is not configured."
    ),
)
async def create_session(
    user: VerifiedUserDep, sessions: AssistantSessionServiceDep
) -> AssistantSessionResponse:
    return AssistantSessionResponse.model_validate(await sessions.create(user_id=user.id))


@router.get(
    "/sessions",
    response_model=list[AssistantSessionResponse],
    responses=error_responses(
        NotAuthenticatedError,
        EmailNotVerifiedError,
        AssistantUnavailableError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Lists the signed-in user's chat sessions, the one with the latest activity first; "
        "`updated_at` moves with every message. Not paginated. Sessions without activity for "
        "a while are deleted. A user whose email is not verified is refused. Unavailable when "
        "the model provider is not configured."
    ),
)
async def list_sessions(
    user: VerifiedUserDep, sessions: AssistantSessionServiceDep
) -> list[AssistantSessionResponse]:
    return [
        AssistantSessionResponse.model_validate(chat_session)
        for chat_session in await sessions.list(user_id=user.id)
    ]


@router.get(
    "/sessions/{session_id}",
    response_model=AssistantSessionDetailResponse,
    responses=error_responses(
        NotAuthenticatedError,
        EmailNotVerifiedError,
        AssistantSessionNotFoundError,
        AssistantUnavailableError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Reads one of the signed-in user's chat sessions with its messages, oldest first; each "
        "message carries its role, `USER` or `ASSISTANT`. Another user's session or an unknown "
        "id is not found. A user whose email is not verified is refused. Unavailable when the "
        "model provider is not configured."
    ),
)
async def get_session(
    session_id: uuid.UUID, user: VerifiedUserDep, sessions: AssistantSessionServiceDep
) -> AssistantSessionDetailResponse:
    return AssistantSessionDetailResponse.model_validate(
        await sessions.get(user_id=user.id, session_id=session_id)
    )


@router.post(
    "/sessions/{session_id}/messages",
    status_code=status.HTTP_200_OK,
    response_class=EventStreamResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "The answer as Server-Sent Events.",
            "content": {EventStreamResponse.MEDIA_TYPE: {"schema": {"type": "string"}}},
        },
        **error_responses(
            NotAuthenticatedError,
            EmailNotVerifiedError,
            AssistantSessionNotFoundError,
            AssistantUnavailableError,
            statuses=DOCUMENTED_ERROR_STATUSES,
            takes_input=True,
        ),
    },
    description=(
        "Sends a message to one of the signed-in user's chat sessions and streams the answer "
        "as Server-Sent Events: `thinking` (`{}`) before every model call, `chunk` "
        '(`{"text"}`) as the answer arrives, then `done` (`{"message_id","created_at"}`) '
        'once the answer is saved, or `error` (`{"code","message"}`) instead of `done`; '
        "then the user's message stays and no answer is saved; the title and `updated_at` are "
        "already set by the question. Error codes: "
        "`ASSISTANT_TIMEOUT` past the turn's time cap, `ASSISTANT_PROVIDER_ERROR` when the "
        "model fails, `SERVER_ERROR` otherwise. A turn is capped in model calls and tool calls; "
        "past a cap a fixed text answers. The first message names the session. Refusals "
        "(sign-in, the session, validation) answer plain JSON before the stream starts. A user "
        "whose email is not verified is refused. Unavailable when the model provider is not "
        "configured."
    ),
)
async def send_message(
    session_id: uuid.UUID, body: AssistantMessageRequest, turn: AssistantTurnServiceDep
) -> EventStreamResponse:
    await turn.start(session_id=session_id, text=body.text)
    return EventStreamResponse(turn.stream())

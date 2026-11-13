import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.common.error_responses import error_responses
from app.features.core.auth.endpoints.dependencies import CurrentUserDep
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.notifications.endpoints.dependencies import NotificationServiceDep
from app.features.core.notifications.endpoints.errors import DOCUMENTED_ERROR_STATUSES
from app.features.core.notifications.endpoints.openapi_tags import NotificationsOpenApiTags
from app.features.core.notifications.schemas import (
    NotificationPageResponse,
    NotificationResponse,
)
from app.features.core.notifications.services.exceptions import NotificationNotFoundError

router = APIRouter(prefix="/notifications", tags=[NotificationsOpenApiTags.NOTIFICATIONS])


@router.get(
    "",
    response_model=NotificationPageResponse,
    responses=error_responses(
        NotAuthenticatedError, statuses=DOCUMENTED_ERROR_STATUSES, takes_input=True
    ),
    description=(
        "Lists the signed-in user's own notifications, newest first; `unread_only` keeps the "
        "unread ones. Each names its kind and the booking it is about. `limit` is 20 by "
        "default and at most 50."
    ),
)
async def list_notifications(
    user: CurrentUserDep,
    notifications: NotificationServiceDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    # Bounded by PostgreSQL bigint: a larger offset overflows in asyncpg and would be a 500.
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> NotificationPageResponse:
    page = await notifications.list_page(
        user_id=user.id, unread_only=unread_only, limit=limit, offset=offset
    )
    return NotificationPageResponse.model_validate(page)


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    responses=error_responses(
        NotAuthenticatedError,
        NotificationNotFoundError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Marks one of the signed-in user's notifications read and returns it. Marking it "
        "again keeps the first read time. Another user's notification is not found."
    ),
)
async def mark_notification_read(
    notification_id: uuid.UUID, user: CurrentUserDep, notifications: NotificationServiceDep
) -> NotificationResponse:
    return NotificationResponse.model_validate(
        await notifications.mark_read(user_id=user.id, notification_id=notification_id)
    )

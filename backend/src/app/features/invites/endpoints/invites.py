import uuid
from typing import Annotated

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.common.error_responses import error_responses
from app.features.core.auth.endpoints.dependencies import CurrentUserDep, OptionalUserDep
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.endpoints.dependencies import GuestCookiesDep, GuestTokenCookie
from app.features.core.bookings.schemas import BookingResponse
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingFullError,
    BookingNotFoundError,
    GuestNameRequiredError,
    InviteClosedError,
)
from app.features.invites.endpoints.dependencies import InviteServiceDep
from app.features.invites.endpoints.errors import DOCUMENTED_ERROR_STATUSES
from app.features.invites.endpoints.openapi_tags import InvitesOpenApiTags
from app.features.invites.schemas import (
    InviteLinkResponse,
    InvitePreviewResponse,
    JoinInviteRequest,
)
from app.features.invites.services.exceptions import InviteNotFoundError

router = APIRouter(tags=[InvitesOpenApiTags.INVITES])


@router.get(
    "/bookings/{booking_id}/invite",
    response_model=InviteLinkResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        BookingAlreadyCancelledError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Gives the owner of a confirmed booking or pending request its invite code for the "
        "`/join/<code>` link. "
        "The code is created on the first request and stays the same afterwards. A booking the "
        "user only joined or another user's booking answers 404."
    ),
)
async def get_invite_link(
    booking_id: uuid.UUID, user: CurrentUserDep, invites: InviteServiceDep
) -> InviteLinkResponse:
    return InviteLinkResponse.model_validate(
        await invites.get_link(user_id=user.id, booking_id=booking_id)
    )


@router.get(
    "/invites/{code}",
    response_model=InvitePreviewResponse,
    responses=error_responses(
        InviteNotFoundError,
        InviteClosedError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Shows who invites and to which booking: the owner's first name, whether the booking "
        "is confirmed or a pending request, the time, the party size, the table and the "
        "location. Closed once the booking is cancelled or shortly before its start. No sign-in "
        "needed."
    ),
)
async def preview_invite(code: str, invites: InviteServiceDep) -> InvitePreviewResponse:
    return InvitePreviewResponse.model_validate(await invites.preview(code=code))


@router.post(
    "/invites/{code}/join",
    response_model=BookingResponse,
    responses=error_responses(
        NotAuthenticatedError,
        InviteNotFoundError,
        InviteClosedError,
        GuestNameRequiredError,
        BookingFullError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Joins the booking of the code and answers it with the caller's role and the "
        "participants. A signed-in user joins under the profile name; the access cookie is "
        "short-lived, so refresh the session first, because a request without it joins as a "
        "guest. Without an account a `name` is required, and the `guest_token` cookie is set "
        "to recognise the guest later, also on other bookings; a guest with a valid cookie "
        "keeps the name and gets the cookie renewed. Joining again changes nothing. Closed "
        "once the booking is cancelled or shortly before its start; refused when the party "
        "is full."
    ),
)
async def join_invite(
    code: str,
    user: OptionalUserDep,
    invites: InviteServiceDep,
    cookies: GuestCookiesDep,
    body: Annotated[JoinInviteRequest | None, Body()] = None,
    guest_token: GuestTokenCookie = None,
) -> JSONResponse:
    outcome = await invites.join(
        code=code,
        user_id=None if user is None else user.id,
        guest_token=guest_token,
        name=None if body is None else body.name,
    )
    response = JSONResponse(BookingResponse.model_validate(outcome.booking).model_dump(mode="json"))
    cookies.set(response=response, token=outcome.guest_token)
    return response

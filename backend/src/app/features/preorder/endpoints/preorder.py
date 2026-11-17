import uuid

from fastapi import APIRouter

from app.common.error_responses import error_responses
from app.features.core.auth.endpoints.dependencies import CurrentUserDep, OptionalUserDep
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.endpoints.dependencies import GuestTokenCookie
from app.features.core.bookings.services.exceptions import BookingNotFoundError
from app.features.core.menu.services.exceptions import DishNotFoundError
from app.features.preorder.endpoints.dependencies import PreorderServiceDep
from app.features.preorder.endpoints.errors import DOCUMENTED_ERROR_STATUSES
from app.features.preorder.endpoints.openapi_tags import PreorderOpenApiTags
from app.features.preorder.schemas import (
    CartResponse,
    GroupPreorderResponse,
    MyPreorderResponse,
    SetCartItemRequest,
    SubmittedPartResponse,
)
from app.features.preorder.services.exceptions import (
    CartEmptyError,
    CartItemNotFoundError,
    DishUnavailableError,
    PreorderClosedError,
    QuantityTooLargeError,
)

router = APIRouter(prefix="/bookings/{booking_id}", tags=[PreorderOpenApiTags.PREORDER])


@router.get(
    "/cart",
    response_model=CartResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Shows the caller's own draft cart for the booking: each dish with its current menu "
        "price, availability and preparation time, the quantity, the note and the line total, "
        "plus the cart total. Open to any participant, a signed-in user or a guest identified "
        "by the `guest_token` cookie, also after the pre-order has closed. A booking the caller "
        "has not joined answers 404."
    ),
)
async def get_cart(
    booking_id: uuid.UUID,
    user: OptionalUserDep,
    preorder: PreorderServiceDep,
    guest_token: GuestTokenCookie = None,
) -> CartResponse:
    cart = await preorder.get_cart(
        booking_id=booking_id, user_id=None if user is None else user.id, guest_token=guest_token
    )
    return CartResponse.model_validate(cart)


@router.put(
    "/cart/items/{dish_id}",
    response_model=CartResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        PreorderClosedError,
        QuantityTooLargeError,
        DishNotFoundError,
        DishUnavailableError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Sets the quantity and the note of one dish in the caller's draft cart, replacing the "
        "previous ones, and answers the cart. A participant is a signed-in user or a guest "
        "identified by the `guest_token` cookie. The quantity runs from one up to a limit; a "
        "blank note means none. A sold-out dish cannot be added or raised, but can be lowered "
        "or have its note changed. Closed while the booking awaits confirmation, once it is "
        "cancelled or shortly before its start."
    ),
)
async def set_cart_item(
    booking_id: uuid.UUID,
    dish_id: uuid.UUID,
    body: SetCartItemRequest,
    user: OptionalUserDep,
    preorder: PreorderServiceDep,
    guest_token: GuestTokenCookie = None,
) -> CartResponse:
    cart = await preorder.set_item(
        booking_id=booking_id,
        user_id=None if user is None else user.id,
        guest_token=guest_token,
        dish_id=dish_id,
        quantity=body.quantity,
        note=body.note,
    )
    return CartResponse.model_validate(cart)


@router.delete(
    "/cart/items/{dish_id}",
    response_model=CartResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        PreorderClosedError,
        CartItemNotFoundError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Removes one dish from the caller's draft cart and answers the cart; works for sold-out "
        "dishes too. A participant is a signed-in user or a guest identified by the "
        "`guest_token` cookie. Closed while the booking awaits confirmation, once it is "
        "cancelled or shortly before its start."
    ),
)
async def remove_cart_item(
    booking_id: uuid.UUID,
    dish_id: uuid.UUID,
    user: OptionalUserDep,
    preorder: PreorderServiceDep,
    guest_token: GuestTokenCookie = None,
) -> CartResponse:
    cart = await preorder.remove_item(
        booking_id=booking_id,
        user_id=None if user is None else user.id,
        guest_token=guest_token,
        dish_id=dish_id,
    )
    return CartResponse.model_validate(cart)


@router.post(
    "/cart/submit",
    response_model=SubmittedPartResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        PreorderClosedError,
        CartEmptyError,
        DishUnavailableError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Submits every line of the caller's draft cart into the booking's group pre-order as "
        "one new part and leaves an empty cart for a new draft. The part is final: its author "
        "cannot change or withdraw it. A participant is a signed-in user or a guest identified "
        "by the `guest_token` cookie. Refused for an empty cart or one with a sold-out dish, "
        "then nothing moves. Closed while the booking awaits confirmation, once it is cancelled "
        "or shortly before its start."
    ),
)
async def submit_cart(
    booking_id: uuid.UUID,
    user: OptionalUserDep,
    preorder: PreorderServiceDep,
    guest_token: GuestTokenCookie = None,
) -> SubmittedPartResponse:
    part = await preorder.submit(
        booking_id=booking_id, user_id=None if user is None else user.id, guest_token=guest_token
    )
    return SubmittedPartResponse.model_validate(part)


@router.get(
    "/my-pre-order",
    response_model=MyPreorderResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Lists the parts the caller has submitted for the booking, oldest first, each with its "
        "lines at the current menu prices and its total, plus the overall total. Only the "
        "caller's own items are shown. Open to any participant, a signed-in user or a guest "
        "identified by the `guest_token` cookie, also after the pre-order has closed."
    ),
)
async def get_my_preorder(
    booking_id: uuid.UUID,
    user: OptionalUserDep,
    preorder: PreorderServiceDep,
    guest_token: GuestTokenCookie = None,
) -> MyPreorderResponse:
    mine = await preorder.get_my_preorder(
        booking_id=booking_id, user_id=None if user is None else user.id, guest_token=guest_token
    )
    return MyPreorderResponse.model_validate(mine)


@router.get(
    "/group-pre-order",
    response_model=GroupPreorderResponse,
    responses=error_responses(
        NotAuthenticatedError,
        BookingNotFoundError,
        statuses=DOCUMENTED_ERROR_STATUSES,
        takes_input=True,
    ),
    description=(
        "Shows the owner of the booking what the whole group has pre-ordered: every participant, "
        "the owner first and then the guests in the order they joined, with their submitted "
        "parts oldest first at the current menu prices and their total, plus the group total. "
        "Drafts are never shown; a participant who has submitted nothing has no parts. Open in "
        "every booking status, also after the pre-order has closed. Only the signed-in owner "
        "reads it: a booking the user only joined or another user's booking answers 404, and a "
        "guest identified only by the `guest_token` cookie is not signed in."
    ),
)
async def get_group_preorder(
    booking_id: uuid.UUID, user: CurrentUserDep, preorder: PreorderServiceDep
) -> GroupPreorderResponse:
    group = await preorder.get_group_preorder(booking_id=booking_id, user_id=user.id)
    return GroupPreorderResponse.model_validate(group)

import dataclasses
import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from app.common.ai_tools import (
    ActionApplier,
    AiToolContext,
    AiToolErrors,
    Card,
    CardField,
    Proposal,
    dry_run,
    invalid_arguments,
    tool_error,
    tool_result,
    usd,
)
from app.features.core.bookings.dto import BookingView
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.preorder.ai_tools.arguments import (
    GetMyPreorderArguments,
    RemoveCartItemArguments,
    SetCartItemArguments,
    SubmitPreorderArguments,
)
from app.features.preorder.ai_tools.cart_remove_item_applier import CartRemoveItemApplier
from app.features.preorder.ai_tools.cart_set_item_applier import CartSetItemApplier
from app.features.preorder.ai_tools.preorder_services import PreorderServices
from app.features.preorder.ai_tools.preorder_submit_applier import PreorderSubmitApplier
from app.features.preorder.dto import CartLineView, CartView
from app.features.preorder.services.exceptions import CartItemNotFoundError


class PreorderTools:
    def __init__(self, context: AiToolContext) -> None:
        self._context = context
        self._services = PreorderServices(context)
        self._schedule = BookingSchedule(context.booking)

    def build(self) -> list[BaseTool]:
        return [
            StructuredTool.from_function(
                coroutine=self._get_my_preorder,
                name="get_my_preorder",
                description=(
                    "Returns the guest's own pre-order for one booking: the cart not yet "
                    "submitted and every part already submitted, each line with the dish, "
                    "quantity, note, current price and line total in USD, the totals of the cart "
                    "and of each part, and the total of all submitted parts."
                ),
                args_schema=GetMyPreorderArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._set_cart_item,
                name="set_cart_item",
                description=(
                    "Proposes setting a dish in the guest's own pre-order cart for one booking "
                    "to a new total quantity, adding the dish when it is not in the cart yet. "
                    "Checks the rules and, when it is possible, shows the guest a card to "
                    "confirm. Nothing changes until the guest applies the card. One proposal per "
                    "answer."
                ),
                args_schema=SetCartItemArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._remove_cart_item,
                name="remove_cart_item",
                description=(
                    "Proposes removing a dish from the guest's own pre-order cart for one "
                    "booking, shown to the guest as a card to confirm. Nothing changes until the "
                    "guest applies the card. One proposal per answer."
                ),
                args_schema=RemoveCartItemArguments,
                handle_validation_error=invalid_arguments,
            ),
            StructuredTool.from_function(
                coroutine=self._submit_preorder,
                name="submit_preorder",
                description=(
                    "Proposes sending the guest's whole pre-order cart for one booking to the "
                    "restaurant as the guest's part, shown as a card to confirm. A sent part is "
                    "final; a new cart can follow. Nothing is sent until the guest applies the "
                    "card. One proposal per answer."
                ),
                args_schema=SubmitPreorderArguments,
                handle_validation_error=invalid_arguments,
            ),
        ]

    def appliers(self) -> dict[str, ActionApplier]:
        return {
            CartSetItemApplier.KIND: CartSetItemApplier(self._context),
            CartRemoveItemApplier.KIND: CartRemoveItemApplier(self._context),
            PreorderSubmitApplier.KIND: PreorderSubmitApplier(self._context),
        }

    async def _get_my_preorder(self, booking_id: uuid.UUID) -> str:
        async with self._context.sessionmaker() as session:
            preorders = self._services.preorders(session)
            cart = await preorders.get_cart(
                booking_id=booking_id, user_id=self._context.user_id, guest_token=None
            )
            submitted = await preorders.get_my_preorder(
                booking_id=booking_id, user_id=self._context.user_id, guest_token=None
            )
        return tool_result(
            {
                "cart": {
                    "items": [self._line(line) for line in cart.items],
                    "total": usd(cart.total_cents),
                },
                "submitted_parts": [
                    {
                        "submitted_at": part.submitted_at.isoformat(),
                        "items": [self._line(line) for line in part.items],
                        "total": usd(part.total_cents),
                    }
                    for part in submitted.parts
                ],
                "submitted_total": usd(submitted.total_cents),
            }
        )

    async def _set_cart_item(
        self, booking_id: uuid.UUID, dish_id: uuid.UUID, quantity: int, note: str | None = None
    ) -> str:
        proposals = self._context.proposals
        if proposals.is_full:
            return tool_error(AiToolErrors.ONE_PROPOSAL_PER_TURN)
        user_id = self._context.user_id
        async with dry_run(self._context.sessionmaker) as session:
            booking = await self._services.participants(session).get_for_participant(
                booking_id=booking_id, user_id=user_id, guest_token=None
            )
            preorders = self._services.preorders(session)
            current = self._line_of(
                await preorders.get_cart(booking_id=booking_id, user_id=user_id, guest_token=None),
                dish_id,
            )
            if note is None:
                note = None if current is None else current.note
            cart = await preorders.set_item(
                booking_id=booking_id,
                user_id=user_id,
                guest_token=None,
                dish_id=dish_id,
                quantity=quantity,
                note=note or None,
            )
        line = next(line for line in cart.items if line.dish.id == dish_id)
        fields = [
            CardField(label="Booking", value=self._booking_label(booking)),
            CardField(label="Dish", value=line.dish.name),
            CardField(label="Quantity", value=str(line.quantity)),
        ]
        if line.note:
            fields.append(CardField(label="Note", value=line.note))
        fields.append(CardField(label="Line total", value=f"${usd(line.line_total_cents)}"))
        if current is not None:
            fields.append(CardField(label="Before", value=self._before(current)))
        card = Card(
            title="Update your pre-order cart", fields=fields, notice=None, confirm_label="Save"
        )
        return self._propose(
            CartSetItemApplier.KIND,
            {
                "booking_id": str(booking_id),
                "dish_id": str(dish_id),
                "quantity": quantity,
                "note": line.note,
                "before": CartSetItemApplier.snapshot(current),
            },
            card,
        )

    async def _remove_cart_item(self, booking_id: uuid.UUID, dish_id: uuid.UUID) -> str:
        proposals = self._context.proposals
        if proposals.is_full:
            return tool_error(AiToolErrors.ONE_PROPOSAL_PER_TURN)
        user_id = self._context.user_id
        async with dry_run(self._context.sessionmaker) as session:
            booking = await self._services.participants(session).get_for_participant(
                booking_id=booking_id, user_id=user_id, guest_token=None
            )
            preorders = self._services.preorders(session)
            removed = self._line_of(
                await preorders.get_cart(booking_id=booking_id, user_id=user_id, guest_token=None),
                dish_id,
            )
            await preorders.remove_item(
                booking_id=booking_id, user_id=user_id, guest_token=None, dish_id=dish_id
            )
        # Only a line added between the read and the service's lock gets here without a line.
        if removed is None:
            raise CartItemNotFoundError()
        card = Card(
            title="Remove from your pre-order cart",
            fields=[
                CardField(label="Booking", value=self._booking_label(booking)),
                CardField(label="Dish", value=removed.dish.name),
                CardField(label="Quantity", value=str(removed.quantity)),
            ],
            notice=None,
            confirm_label="Remove",
        )
        return self._propose(
            CartRemoveItemApplier.KIND,
            {"booking_id": str(booking_id), "dish_id": str(dish_id)},
            card,
        )

    async def _submit_preorder(self, booking_id: uuid.UUID) -> str:
        proposals = self._context.proposals
        if proposals.is_full:
            return tool_error(AiToolErrors.ONE_PROPOSAL_PER_TURN)
        user_id = self._context.user_id
        async with dry_run(self._context.sessionmaker) as session:
            booking = await self._services.participants(session).get_for_participant(
                booking_id=booking_id, user_id=user_id, guest_token=None
            )
            part = await self._services.preorders(session).submit(
                booking_id=booking_id, user_id=user_id, guest_token=None
            )
        items = ", ".join(f"{line.quantity} × {line.dish.name}" for line in part.items)
        card = Card(
            title="Send your pre-order",
            fields=[
                CardField(label="Booking", value=self._booking_label(booking)),
                CardField(label="Items", value=items),
                CardField(label="Total", value=f"${usd(part.total_cents)}"),
            ],
            notice="A sent part is final; a new cart can follow.",
            confirm_label="Send",
        )
        return self._propose(
            PreorderSubmitApplier.KIND,
            {
                "booking_id": str(booking_id),
                "items": [
                    {"dish_id": str(line.dish.id), "quantity": line.quantity} for line in part.items
                ],
                "total_cents": part.total_cents,
            },
            card,
        )

    def _propose(self, kind: str, payload: dict[str, Any], card: Card) -> str:
        self._context.proposals.hold(Proposal(kind=kind, payload=payload, card=card))
        return tool_result({"status": "awaiting_confirmation", "card": dataclasses.asdict(card)})

    @staticmethod
    def _before(line: CartLineView) -> str:
        if line.note:
            return f"{line.quantity}, note: {line.note}"
        return str(line.quantity)

    def _booking_label(self, booking: BookingView) -> str:
        start = self._schedule.to_local(booking.starts_at)
        return f"{start:%a, %d %b %Y, %H:%M}, {booking.location.address}"

    @staticmethod
    def _line_of(cart: CartView, dish_id: uuid.UUID) -> CartLineView | None:
        return next((line for line in cart.items if line.dish.id == dish_id), None)

    @staticmethod
    def _line(line: CartLineView) -> dict[str, Any]:
        return {
            "dish_id": str(line.dish.id),
            "name": line.dish.name,
            "quantity": line.quantity,
            "note": line.note,
            "price": usd(line.dish.price_cents),
            "line_total": usd(line.line_total_cents),
            "is_available": line.dish.is_available,
        }

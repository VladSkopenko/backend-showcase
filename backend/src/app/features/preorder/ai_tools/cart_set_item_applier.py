import uuid
from typing import Any

from app.common.ai_tools import ActionContext, AiToolContext, usd
from app.features.preorder.ai_tools.preorder_services import PreorderServices
from app.features.preorder.dto import CartLineView
from app.features.preorder.services.exceptions import CartChangedError


class CartSetItemApplier:
    """Applies a confirmed `cart.set_item` card, unless the line changed since the card."""

    KIND = "cart.set_item"

    def __init__(self, context: AiToolContext) -> None:
        self._services = PreorderServices(context)

    @staticmethod
    def snapshot(line: CartLineView | None) -> dict[str, Any] | None:
        """The line as the card saw it; None when the dish was not in the cart."""
        if line is None:
            return None
        return {"quantity": line.quantity, "note": line.note}

    async def apply(self, context: ActionContext) -> dict[str, Any]:
        payload = context.payload
        booking_id = uuid.UUID(payload["booking_id"])
        dish_id = uuid.UUID(payload["dish_id"])
        # The same lock the cart's writes take, so no website change lands between check and write.
        await self._services.participants(context.session).lock_participant(
            booking_id=booking_id, user_id=context.user_id, guest_token=None
        )
        preorders = self._services.preorders(context.session)
        cart = await preorders.get_cart(
            booking_id=booking_id, user_id=context.user_id, guest_token=None
        )
        current = next((line for line in cart.items if line.dish.id == dish_id), None)
        if self.snapshot(current) != payload["before"]:
            raise CartChangedError()
        cart = await preorders.set_item(
            booking_id=booking_id,
            user_id=context.user_id,
            guest_token=None,
            dish_id=dish_id,
            quantity=payload["quantity"],
            note=payload["note"],
        )
        return {"booking_id": payload["booking_id"], "cart_total": usd(cart.total_cents)}

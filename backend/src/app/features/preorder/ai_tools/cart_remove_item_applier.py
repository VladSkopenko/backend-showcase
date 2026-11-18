import uuid
from typing import Any

from app.common.ai_tools import ActionContext, AiToolContext, usd
from app.features.preorder.ai_tools.preorder_services import PreorderServices


class CartRemoveItemApplier:
    """Applies a confirmed `cart.remove_item` card through the route's own service."""

    KIND = "cart.remove_item"

    def __init__(self, context: AiToolContext) -> None:
        self._services = PreorderServices(context)

    async def apply(self, context: ActionContext) -> dict[str, Any]:
        payload = context.payload
        cart = await self._services.preorders(context.session).remove_item(
            booking_id=uuid.UUID(payload["booking_id"]),
            user_id=context.user_id,
            guest_token=None,
            dish_id=uuid.UUID(payload["dish_id"]),
        )
        return {"booking_id": payload["booking_id"], "cart_total": usd(cart.total_cents)}

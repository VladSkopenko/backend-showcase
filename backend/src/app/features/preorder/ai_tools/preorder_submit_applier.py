import uuid
from typing import Any

from app.common.ai_tools import ActionContext, AiToolContext, usd
from app.features.preorder.ai_tools.preorder_services import PreorderServices
from app.features.preorder.services.exceptions import CartChangedError


class PreorderSubmitApplier:
    KIND = "preorder.submit"

    def __init__(self, context: AiToolContext) -> None:
        self._services = PreorderServices(context)

    async def apply(self, context: ActionContext) -> dict[str, Any]:
        payload = context.payload
        part = await self._services.preorders(context.session).submit(
            booking_id=uuid.UUID(payload["booking_id"]), user_id=context.user_id, guest_token=None
        )
        submitted = {str(line.dish.id): line.quantity for line in part.items}
        pinned = {item["dish_id"]: item["quantity"] for item in payload["items"]}
        if submitted != pinned or part.total_cents != payload["total_cents"]:
            raise CartChangedError()
        return {
            "booking_id": payload["booking_id"],
            "part_id": str(part.id),
            "total": usd(part.total_cents),
        }

import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai_tools import AiToolContext, invalid_arguments, tool_result, usd
from app.features.core.bookings.services.participant_service import ParticipantService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.menu.services.dish_catalog_service import DishCatalogService
from app.features.preorder.ai_tools.arguments import GetMyPreorderArguments
from app.features.preorder.dto import CartLineView
from app.features.preorder.services.preorder_service import PreorderService


class PreorderTools:
    def __init__(self, context: AiToolContext) -> None:
        self._context = context

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
            )
        ]

    async def _get_my_preorder(self, booking_id: uuid.UUID) -> str:
        async with self._context.sessionmaker() as session:
            preorders = self._preorders(session)
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

    def _preorders(self, session: AsyncSession) -> PreorderService:
        booking = self._context.booking
        locations = LocationCatalogService(session, public_base_url=self._context.public_base_url)
        return PreorderService(
            session,
            ParticipantService(session, locations, booking),
            DishCatalogService(session, public_base_url=self._context.public_base_url),
            max_item_quantity=self._context.max_item_quantity,
            timezone=booking.timezone,
        )

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

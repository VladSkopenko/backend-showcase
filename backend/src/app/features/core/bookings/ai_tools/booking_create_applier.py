import datetime
import uuid
from typing import Any

from app.common.ai_tools import ActionContext, AiToolContext
from app.features.core.bookings.services.booking_service import BookingService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class BookingCreateApplier:
    """Applies a confirmed `booking.create` card through the route's own service."""

    KIND = "booking.create"

    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    async def apply(self, context: ActionContext) -> dict[str, Any]:
        locations = LocationCatalogService(
            context.session, public_base_url=self._context.public_base_url
        )
        booking = await BookingService(context.session, locations, self._context.booking).create(
            user_id=context.user_id,
            table_id=uuid.UUID(context.payload["table_id"]),
            starts_at=datetime.datetime.fromisoformat(context.payload["starts_at"]),
            party_size=context.payload["party_size"],
        )
        return {"booking_id": str(booking.id), "status": booking.status.value}

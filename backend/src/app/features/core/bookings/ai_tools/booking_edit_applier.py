import datetime
import uuid
from typing import Any

from app.common.ai_tools import ActionContext, AiToolContext
from app.features.core.bookings.dto import ExpectedBooking
from app.features.core.bookings.services.booking_service import BookingService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class BookingEditApplier:
    KIND = "booking.edit"

    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    async def apply(self, context: ActionContext) -> dict[str, Any]:
        payload = context.payload
        before = payload["before"]
        locations = LocationCatalogService(
            context.session, public_base_url=self._context.public_base_url
        )
        booking = await BookingService(context.session, locations, self._context.booking).edit(
            user_id=context.user_id,
            booking_id=uuid.UUID(payload["booking_id"]),
            starts_at=datetime.datetime.fromisoformat(payload["starts_at"]),
            party_size=payload["party_size"],
            duration_minutes=payload["duration_minutes"],
            expected=ExpectedBooking(
                starts_at=datetime.datetime.fromisoformat(before["starts_at"]),
                party_size=before["party_size"],
                duration_minutes=before["duration_minutes"],
            ),
        )
        return {"booking_id": str(booking.id), "status": booking.status.value}

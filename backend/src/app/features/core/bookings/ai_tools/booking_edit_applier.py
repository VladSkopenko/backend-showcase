import datetime
import uuid
from typing import Any

from app.common.ai_tools import ActionContext, AiToolContext
from app.features.core.bookings.services.booking_service import BookingService
from app.features.core.bookings.services.exceptions import BookingChangedError
from app.features.core.bookings.services.participant_service import ParticipantService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class BookingEditApplier:
    """Applies a confirmed `booking.edit` card, unless the booking changed since the card."""

    KIND = "booking.edit"

    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    async def apply(self, context: ActionContext) -> dict[str, Any]:
        payload = context.payload
        booking_id = uuid.UUID(payload["booking_id"])
        locations = LocationCatalogService(
            context.session, public_base_url=self._context.public_base_url
        )
        participants = ParticipantService(context.session, locations, self._context.booking)
        await participants.lock_owned(user_id=context.user_id, booking_id=booking_id)
        current = await participants.get_for_participant(
            booking_id=booking_id, user_id=context.user_id, guest_token=None
        )
        before = payload["before"]
        if (
            current.starts_at != datetime.datetime.fromisoformat(before["starts_at"])
            or current.party_size != before["party_size"]
            or current.ends_at - current.starts_at
            != datetime.timedelta(minutes=before["duration_minutes"])
        ):
            raise BookingChangedError()
        booking = await BookingService(context.session, locations, self._context.booking).edit(
            user_id=context.user_id,
            booking_id=booking_id,
            starts_at=datetime.datetime.fromisoformat(payload["starts_at"]),
            party_size=payload["party_size"],
            duration_minutes=payload["duration_minutes"],
        )
        return {"booking_id": str(booking.id), "status": booking.status.value}

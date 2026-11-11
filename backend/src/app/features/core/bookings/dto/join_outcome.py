from dataclasses import dataclass

from app.features.core.bookings.dto.booking_view import BookingView


@dataclass(frozen=True)
class JoinOutcome:
    booking: BookingView
    guest_token: str | None

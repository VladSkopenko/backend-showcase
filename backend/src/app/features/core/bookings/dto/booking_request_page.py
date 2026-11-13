from dataclasses import dataclass

from app.features.core.bookings.dto.booking_request_view import BookingRequestView


@dataclass(frozen=True)
class BookingRequestPage:
    items: list[BookingRequestView]
    total: int
    limit: int
    offset: int

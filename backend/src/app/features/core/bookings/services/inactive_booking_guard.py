from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingRejectedError,
)


class InactiveBookingGuard:
    def check_active(self, *, status: BookingStatus) -> None:
        if status.is_active:
            return
        if status == BookingStatus.REJECTED:
            raise BookingRejectedError()
        raise BookingAlreadyCancelledError()

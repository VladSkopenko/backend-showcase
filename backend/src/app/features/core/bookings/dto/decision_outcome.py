from dataclasses import dataclass

from app.features.core.bookings.dto.booking_request_view import BookingRequestView
from app.features.core.notifications.dto import DecisionNotice


@dataclass(frozen=True)
class DecisionOutcome:
    view: BookingRequestView
    notices: list[DecisionNotice]

from app.common.errors import DomainError


class PartyTooLargeError(DomainError):
    code = "PARTY_TOO_LARGE"

    def __init__(self) -> None:
        super().__init__("Parties this large cannot be booked online. Please call the restaurant.")


class DateOutOfRangeError(DomainError):
    code = "DATE_OUT_OF_RANGE"

    def __init__(self) -> None:
        super().__init__("Bookings can be made only from today up to the booking horizon.")


class SlotInvalidError(DomainError):
    code = "SLOT_INVALID"

    def __init__(self) -> None:
        super().__init__("Choose one of the offered start times.")


class TableNotFoundError(DomainError):
    code = "TABLE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No table with this id exists.")


class TableNotSuitableError(DomainError):
    code = "TABLE_NOT_SUITABLE"

    def __init__(self) -> None:
        super().__init__("This table cannot be booked online for this party size.")


class SlotUnavailableError(DomainError):
    code = "SLOT_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("This table is not available at this time.")


class OverlappingBookingError(DomainError):
    code = "OVERLAPPING_BOOKING"

    def __init__(self) -> None:
        super().__init__("You already have a booking at this time.")


class BookingNotFoundError(DomainError):
    code = "BOOKING_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No booking with this id exists.")


class BookingAlreadyCancelledError(DomainError):
    code = "BOOKING_ALREADY_CANCELLED"

    def __init__(self) -> None:
        super().__init__("This booking is already cancelled.")


class CancellationClosedError(DomainError):
    code = "CANCELLATION_CLOSED"

    def __init__(self) -> None:
        super().__init__("This booking starts too soon to be cancelled online.")


class EditClosedError(DomainError):
    code = "EDIT_CLOSED"

    def __init__(self) -> None:
        super().__init__("This booking starts too soon to be changed online.")


class DayChangeNotAllowedError(DomainError):
    code = "DAY_CHANGE_NOT_ALLOWED"

    def __init__(self) -> None:
        super().__init__("A booking can be moved only within its day.")


class DurationInvalidError(DomainError):
    code = "DURATION_INVALID"

    def __init__(self) -> None:
        super().__init__("Choose one of the offered durations.")


class EndsAfterClosingError(DomainError):
    code = "ENDS_AFTER_CLOSING"

    def __init__(self) -> None:
        super().__init__("This stay would end after the restaurant closes.")


class InviteClosedError(DomainError):
    code = "INVITE_CLOSED"

    def __init__(self) -> None:
        super().__init__("This invitation is closed: the booking was cancelled or starts soon.")


class BookingFullError(DomainError):
    code = "BOOKING_FULL"

    def __init__(self) -> None:
        super().__init__("Everyone this booking has room for has already joined.")


class GuestNameRequiredError(DomainError):
    code = "GUEST_NAME_REQUIRED"

    def __init__(self) -> None:
        super().__init__("Enter your name to join.")


class PartyBelowParticipantsError(DomainError):
    code = "PARTY_BELOW_PARTICIPANTS"

    def __init__(self) -> None:
        super().__init__("The party cannot be smaller than the people who have already joined.")

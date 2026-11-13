from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

from app.common import clock
from app.config.settings import BookingSettings
from app.features.core.bookings.enums import BookingStatus
from app.features.core.bookings.models import Booking
from app.features.core.bookings.services.exceptions import (
    CancellationClosedError,
    DateOutOfRangeError,
    DayChangeNotAllowedError,
    DurationInvalidError,
    EditClosedError,
    EndsAfterClosingError,
    InviteClosedError,
    PartyTooLargeError,
    SlotInvalidError,
)


class BookingSchedule:
    def __init__(self, settings: BookingSettings) -> None:
        self._settings = settings
        self.duration = timedelta(minutes=settings.duration_minutes)
        self._max_party_size = settings.max_online_party_size
        self._max_request_party_size = settings.max_request_party_size
        first = settings.first_slot.hour * 60 + settings.first_slot.minute
        last = settings.last_slot.hour * 60 + settings.last_slot.minute
        self._slot_times = tuple(
            time(minutes // 60, minutes % 60)
            for minutes in range(first, last + 1, settings.slot_minutes)
        )
        self._duration_minutes = range(
            settings.duration_minutes, settings.max_duration_minutes + 1, settings.slot_minutes
        )

    def now(self) -> datetime:
        return self.to_local(clock.now())

    def to_local(self, moment: datetime) -> datetime:
        return moment.astimezone(self._settings.timezone)

    def start_at(self, *, day: date, slot_time: time) -> datetime:
        return datetime.combine(day, slot_time, tzinfo=self._settings.timezone)

    def starts_on(self, *, day: date) -> list[datetime]:
        return [self.start_at(day=day, slot_time=slot_time) for slot_time in self._slot_times]

    def is_free(
        self, *, start: datetime, duration: timedelta, bookings: Sequence[Booking], now: datetime
    ) -> bool:
        end = start + duration
        return (
            start > now
            and self._ends_by_closing(start=start, end=end)
            and not any(booking.starts_at < end and booking.ends_at > start for booking in bookings)
        )

    def check_party_size(self, *, party_size: int) -> None:
        if party_size > self._max_party_size:
            raise PartyTooLargeError()

    def check_requestable_party_size(self, *, party_size: int) -> None:
        if party_size > self._max_request_party_size:
            raise PartyTooLargeError()

    def max_capacity(self, *, party_size: int) -> int:
        if self._is_request(party_size=party_size):
            return self._max_request_party_size
        return self._max_party_size

    def is_request_table(self, *, capacity: int) -> bool:
        return capacity > self._max_party_size

    def initial_status(self, *, party_size: int) -> BookingStatus:
        if self._is_request(party_size=party_size):
            return BookingStatus.PENDING
        return BookingStatus.CONFIRMED

    def check_date(self, *, day: date) -> None:
        today = self.now().date()
        if not today <= day <= today + timedelta(days=self._settings.horizon_days):
            raise DateOutOfRangeError()

    def check_slot_time(self, *, slot_time: time) -> None:
        if slot_time not in self._slot_times:
            raise SlotInvalidError()

    def check_same_day(self, *, start: datetime, current_start: datetime) -> None:
        if self.to_local(start).date() != self.to_local(current_start).date():
            raise DayChangeNotAllowedError()

    def check_duration(self, *, duration_minutes: int) -> None:
        if duration_minutes not in self._duration_minutes:
            raise DurationInvalidError()

    def check_ends_by_closing(self, *, start: datetime, end: datetime) -> None:
        if not self._ends_by_closing(start=start, end=end):
            raise EndsAfterClosingError()

    def check_cancellable(self, *, starts_at: datetime) -> None:
        if self._cutoff_passed(starts_at=starts_at):
            raise CancellationClosedError()

    def check_editable(self, *, starts_at: datetime) -> None:
        if self._cutoff_passed(starts_at=starts_at):
            raise EditClosedError()

    def check_joinable(self, *, starts_at: datetime) -> None:
        if not self.preorder_open(starts_at=starts_at):
            raise InviteClosedError()

    def preorder_open(self, *, starts_at: datetime) -> bool:
        return starts_at - clock.now() >= timedelta(minutes=self._settings.preorder_lock_minutes)

    def _is_request(self, *, party_size: int) -> bool:
        return party_size > self._max_party_size

    def _cutoff_passed(self, *, starts_at: datetime) -> bool:
        return starts_at - clock.now() < timedelta(minutes=self._settings.cancel_cutoff_minutes)

    def _ends_by_closing(self, *, start: datetime, end: datetime) -> bool:
        closing = datetime.combine(
            self.to_local(start).date(), self._settings.closing_time, tzinfo=self._settings.timezone
        )
        return end <= closing

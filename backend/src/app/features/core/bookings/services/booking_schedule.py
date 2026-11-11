from datetime import date, datetime, time, timedelta

from app.common import clock
from app.config.settings import BookingSettings
from app.features.core.bookings.services.exceptions import (
    CancellationClosedError,
    DateOutOfRangeError,
    PartyTooLargeError,
    SlotInvalidError,
)


class BookingSchedule:
    def __init__(self, settings: BookingSettings) -> None:
        self._settings = settings
        self.duration = timedelta(minutes=settings.duration_minutes)
        self.max_party_size = settings.max_online_party_size
        first = settings.first_slot.hour * 60 + settings.first_slot.minute
        last = settings.last_slot.hour * 60 + settings.last_slot.minute
        self._slot_times = tuple(
            time(minutes // 60, minutes % 60)
            for minutes in range(first, last + 1, settings.slot_minutes)
        )

    def now(self) -> datetime:
        return self.to_local(clock.now())

    def to_local(self, moment: datetime) -> datetime:
        return moment.astimezone(self._settings.timezone)

    def start_at(self, *, day: date, slot_time: time) -> datetime:
        return datetime.combine(day, slot_time, tzinfo=self._settings.timezone)

    def starts_on(self, *, day: date) -> list[datetime]:
        return [self.start_at(day=day, slot_time=slot_time) for slot_time in self._slot_times]

    def check_party_size(self, *, party_size: int) -> None:
        if party_size > self.max_party_size:
            raise PartyTooLargeError()

    def check_date(self, *, day: date) -> None:
        today = self.now().date()
        if not today <= day <= today + timedelta(days=self._settings.horizon_days):
            raise DateOutOfRangeError()

    def check_slot_time(self, *, slot_time: time) -> None:
        if slot_time not in self._slot_times:
            raise SlotInvalidError()

    def check_cancellable(self, *, starts_at: datetime) -> None:
        if starts_at - clock.now() < timedelta(minutes=self._settings.cancel_cutoff_minutes):
            raise CancellationClosedError()

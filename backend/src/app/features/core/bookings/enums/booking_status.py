import enum


class BookingStatus(enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    PENDING = "PENDING"

    @classmethod
    def active(cls) -> frozenset[BookingStatus]:
        return frozenset({cls.CONFIRMED, cls.PENDING})

    @property
    def is_active(self) -> bool:
        return self in BookingStatus.active()

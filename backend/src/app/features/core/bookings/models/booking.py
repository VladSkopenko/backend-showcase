import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base
from app.features.core.bookings.enums import BookingStatus, ParticipantRole


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # The naming convention has no key for exclusion constraints, so the name is explicit.
        # tstzrange defaults to [) bounds: a booking ending at 13:30 and one starting then fit.
        ExcludeConstraint(
            (column("table_id"), "="),
            (func.tstzrange(column("starts_at"), column("ends_at")), "&&"),
            name="ex_bookings_table_id_period",
            using="gist",
            where=text("status = 'CONFIRMED'"),
        ),
        CheckConstraint("ends_at > starts_at", name="ends_at_after_starts_at"),
        CheckConstraint("party_size BETWEEN 1 AND 8", name="party_size_between_1_and_8"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dining_tables.id", ondelete="CASCADE"))
    party_size: Mapped[int]
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"), server_default=BookingStatus.CONFIRMED.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(50))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BookingParticipant(Base):
    __tablename__ = "booking_participants"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, guest_id) = 1", name="one_of_user_id_guest_id"),
        UniqueConstraint(
            "booking_id", "user_id", name="uq_booking_participants_booking_id_user_id"
        ),
        UniqueConstraint(
            "booking_id", "guest_id", name="uq_booking_participants_booking_id_guest_id"
        ),
        Index(
            "ix_booking_participants_booking_id_owner",
            "booking_id",
            unique=True,
            postgresql_where=text("role = 'OWNER'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    guest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("guests.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ParticipantRole] = mapped_column(Enum(ParticipantRole, name="participant_role"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

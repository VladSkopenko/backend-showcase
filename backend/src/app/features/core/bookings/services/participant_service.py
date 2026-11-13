import hashlib
import secrets
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.config.settings import BookingSettings
from app.features.core.auth.services.exceptions import NotAuthenticatedError
from app.features.core.bookings.dto import (
    BookedTableView,
    BookingView,
    InvitePreviewView,
    JoinOutcome,
    OwnedBooking,
    ParticipantAccess,
)
from app.features.core.bookings.enums import BookingStatus, ParticipantRole
from app.features.core.bookings.models import Booking, BookingParticipant, Guest
from app.features.core.bookings.repositories import (
    BookingParticipantRepository,
    BookingRepository,
    GuestRepository,
)
from app.features.core.bookings.services.booking_schedule import BookingSchedule
from app.features.core.bookings.services.booking_view_builder import BookingViewBuilder
from app.features.core.bookings.services.exceptions import (
    BookingAlreadyCancelledError,
    BookingFullError,
    BookingNotFoundError,
    GuestNameRequiredError,
    InviteClosedError,
)
from app.features.core.locations.models import DiningTable
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.users.repositories import UserRepository


class ParticipantService:
    def __init__(
        self, session: AsyncSession, locations: LocationCatalogService, settings: BookingSettings
    ) -> None:
        self._bookings = BookingRepository(session)
        self._participants = BookingParticipantRepository(session)
        self._guests = GuestRepository(session)
        self._users = UserRepository(session)
        self._locations = locations
        self._schedule = BookingSchedule(settings)
        self._views = BookingViewBuilder(session, locations, self._schedule)
        self._guest_ttl = timedelta(days=settings.guest_token_ttl_days)

    async def lock_owned(self, *, user_id: uuid.UUID, booking_id: uuid.UUID) -> OwnedBooking:
        row = await self._bookings.get_for_user(
            booking_id=booking_id, user_id=user_id, for_update=True
        )
        if row is None:
            raise BookingNotFoundError()
        booking, _, _ = row
        if not booking.status.is_active:
            raise BookingAlreadyCancelledError()
        return OwnedBooking(id=booking.id)

    async def preview(self, *, booking_id: uuid.UUID) -> InvitePreviewView:
        booking, table = await self._get(booking_id=booking_id)
        self._check_joinable(booking)
        owner = await self._users.get_by_id(user_id=booking.user_id)
        if owner is None:
            raise BookingNotFoundError()
        return InvitePreviewView(
            owner_first_name=owner.first_name,
            status=booking.status,
            starts_at=self._schedule.to_local(booking.starts_at),
            ends_at=self._schedule.to_local(booking.ends_at),
            party_size=booking.party_size,
            table=BookedTableView(id=table.id, label=table.label, capacity=table.capacity),
            location=await self._locations.get(location_id=table.location_id),
        )

    async def join(
        self,
        *,
        booking_id: uuid.UUID,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        name: str | None,
    ) -> JoinOutcome:
        guest = None
        if user_id is not None:
            await self._users.get_by_id(user_id=user_id, for_update=True)
        else:
            guest = await self._find_guest(guest_token=guest_token)
        booking, table = await self._get(booking_id=booking_id, for_update=True)
        self._check_joinable(booking)
        if user_id is not None or guest is not None:
            existing = await self._participants.find(
                booking_id=booking.id,
                user_id=user_id,
                guest_id=None if guest is None else guest.id,
            )
            if existing is not None:
                view = await self._views.one(
                    booking=booking, table=table, role=existing.role, participant_id=existing.id
                )
                return JoinOutcome(booking=view, guest_token=None)
        if user_id is None and guest is None and not name:
            raise GuestNameRequiredError()
        if await self._participants.count(booking_id=booking.id) >= booking.party_size:
            raise BookingFullError()
        token = None
        if user_id is None:
            guest, token = await self._create_or_renew_guest(
                guest=guest, guest_token=guest_token, name=name
            )
        participant = BookingParticipant(
            booking_id=booking.id,
            user_id=user_id,
            guest_id=None if guest is None else guest.id,
            role=ParticipantRole.GUEST,
            created_at=clock.now(),
        )
        await self._participants.add(participant=participant)
        view = await self._views.one(
            booking=booking, table=table, role=ParticipantRole.GUEST, participant_id=participant.id
        )
        return JoinOutcome(booking=view, guest_token=token)

    async def get_for_participant(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_token: str | None
    ) -> BookingView:
        guest_id = await self._caller_guest_id(user_id=user_id, guest_token=guest_token)
        row = await self._bookings.get_for_participant(
            booking_id=booking_id, user_id=user_id, guest_id=guest_id
        )
        if row is None:
            raise BookingNotFoundError()
        booking, table, role, participant_id = row
        return await self._views.one(
            booking=booking, table=table, role=role, participant_id=participant_id
        )

    async def get_participant(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_token: str | None
    ) -> ParticipantAccess:
        return await self._participant(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token, for_update=False
        )

    async def lock_participant(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_token: str | None
    ) -> ParticipantAccess:
        return await self._participant(
            booking_id=booking_id, user_id=user_id, guest_token=guest_token, for_update=True
        )

    async def _participant(
        self,
        *,
        booking_id: uuid.UUID,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        for_update: bool,
    ) -> ParticipantAccess:
        guest_id = await self._caller_guest_id(user_id=user_id, guest_token=guest_token)
        row = await self._bookings.get_participation(
            booking_id=booking_id, user_id=user_id, guest_id=guest_id, for_update=for_update
        )
        if row is None:
            raise BookingNotFoundError()
        booking, participant_id = row
        return ParticipantAccess(
            participant_id=participant_id,
            preorder_open=booking.status == BookingStatus.CONFIRMED
            and self._schedule.preorder_open(starts_at=booking.starts_at),
        )

    async def _caller_guest_id(
        self, *, user_id: uuid.UUID | None, guest_token: str | None
    ) -> uuid.UUID | None:
        if user_id is not None:
            return None
        guest = await self._find_guest(guest_token=guest_token)
        if guest is None:
            raise NotAuthenticatedError()
        return guest.id

    async def _get(
        self, *, booking_id: uuid.UUID, for_update: bool = False
    ) -> tuple[Booking, DiningTable]:
        row = await self._bookings.get(booking_id=booking_id, for_update=for_update)
        if row is None:
            raise BookingNotFoundError()
        return row

    def _check_joinable(self, booking: Booking) -> None:
        if not booking.status.is_active:
            raise InviteClosedError()
        self._schedule.check_joinable(starts_at=booking.starts_at)

    async def _find_guest(self, *, guest_token: str | None) -> Guest | None:
        if guest_token is None:
            return None
        guest = await self._guests.get_by_token_hash(token_hash=self._hash_token(guest_token))
        if guest is None or guest.expires_at <= clock.now():
            return None
        return guest

    async def _create_or_renew_guest(
        self, *, guest: Guest | None, guest_token: str | None, name: str | None
    ) -> tuple[Guest, str]:
        expires_at = clock.now() + self._guest_ttl
        if guest is not None and guest_token is not None:
            guest.expires_at = expires_at
            return guest, guest_token
        token = secrets.token_urlsafe(32)
        guest = Guest(name=name, token_hash=self._hash_token(token), expires_at=expires_at)
        await self._guests.add(guest=guest)
        return guest, token

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

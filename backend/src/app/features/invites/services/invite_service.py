import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.common import clock
from app.features.core.bookings.dto import InvitePreviewView, JoinOutcome
from app.features.core.bookings.services.participant_service import ParticipantService
from app.features.invites.models import BookingInvite
from app.features.invites.repositories import BookingInviteRepository
from app.features.invites.services.exceptions import InviteNotFoundError


class InviteService:
    def __init__(self, session: AsyncSession, participants: ParticipantService) -> None:
        self._invites = BookingInviteRepository(session)
        self._participants = participants

    async def get_link(self, *, user_id: uuid.UUID, booking_id: uuid.UUID) -> BookingInvite:
        booking = await self._participants.lock_owned(user_id=user_id, booking_id=booking_id)
        invite = await self._invites.get_by_booking_id(booking_id=booking.id)
        if invite is None:
            invite = BookingInvite(
                booking_id=booking.id, code=secrets.token_urlsafe(16), created_at=clock.now()
            )
            await self._invites.add(invite=invite)
        return invite

    async def preview(self, *, code: str) -> InvitePreviewView:
        invite = await self._get(code=code)
        return await self._participants.preview(booking_id=invite.booking_id)

    async def join(
        self,
        *,
        code: str,
        user_id: uuid.UUID | None,
        guest_token: str | None,
        name: str | None,
    ) -> JoinOutcome:
        invite = await self._get(code=code)
        return await self._participants.join(
            booking_id=invite.booking_id, user_id=user_id, guest_token=guest_token, name=name
        )

    async def _get(self, *, code: str) -> BookingInvite:
        invite = await self._invites.get_by_code(code=code)
        if invite is None:
            raise InviteNotFoundError()
        return invite

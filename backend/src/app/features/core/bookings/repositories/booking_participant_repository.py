import uuid
from collections.abc import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.core.bookings.enums import ParticipantRole
from app.features.core.bookings.models import BookingParticipant, Guest
from app.features.core.users.models import User


class BookingParticipantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, participant: BookingParticipant) -> None:
        self._session.add(participant)
        await self._session.flush()

    async def count(self, *, booking_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(BookingParticipant)
            .where(BookingParticipant.booking_id == booking_id)
        )
        return count or 0

    async def find(
        self, *, booking_id: uuid.UUID, user_id: uuid.UUID | None, guest_id: uuid.UUID | None
    ) -> BookingParticipant | None:
        identity = (
            BookingParticipant.user_id == user_id
            if user_id is not None
            else BookingParticipant.guest_id == guest_id
        )
        participant: BookingParticipant | None = await self._session.scalar(
            select(BookingParticipant).where(BookingParticipant.booking_id == booking_id, identity)
        )
        return participant

    async def list_named(
        self, *, booking_ids: Sequence[uuid.UUID]
    ) -> Sequence[tuple[BookingParticipant, str]]:
        rows = await self._session.execute(
            select(BookingParticipant, func.coalesce(User.first_name, Guest.name))
            .outerjoin(User, User.id == BookingParticipant.user_id)
            .outerjoin(Guest, Guest.id == BookingParticipant.guest_id)
            .where(BookingParticipant.booking_id.in_(booking_ids))
            .order_by(
                case((BookingParticipant.role == ParticipantRole.OWNER, 0), else_=1),
                BookingParticipant.created_at,
                BookingParticipant.id,
            )
        )
        return [(participant, name) for participant, name in rows]

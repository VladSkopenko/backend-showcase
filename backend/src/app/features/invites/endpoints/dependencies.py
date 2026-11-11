from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.features.core.bookings.endpoints.dependencies import ParticipantServiceDep
from app.features.invites.services.invite_service import InviteService

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_invite_service(session: SessionDep, participants: ParticipantServiceDep) -> InviteService:
    return InviteService(session, participants)


InviteServiceDep = Annotated[InviteService, Depends(get_invite_service)]

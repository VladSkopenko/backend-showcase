from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.core.bookings.endpoints.dependencies import ParticipantServiceDep
from app.features.core.menu.endpoints.dependencies import DishCatalogServiceDep
from app.features.preorder.services.preorder_service import PreorderService

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_preorder_service(
    session: SessionDep,
    participants: ParticipantServiceDep,
    dishes: DishCatalogServiceDep,
    settings: SettingsDep,
) -> PreorderService:
    return PreorderService(
        session,
        participants,
        dishes,
        max_item_quantity=settings.preorder.max_item_quantity,
        timezone=settings.booking.timezone,
    )


PreorderServiceDep = Annotated[PreorderService, Depends(get_preorder_service)]

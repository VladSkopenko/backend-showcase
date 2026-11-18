from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.core.bookings.endpoints.cookies import GuestCookies
from app.features.core.bookings.services.booking_request_service import BookingRequestService
from app.features.core.bookings.services.booking_service import BookingService
from app.features.core.bookings.services.participant_service import ParticipantService
from app.features.core.bookings.services.table_search_service import TableSearchService
from app.features.core.locations.endpoints.dependencies import LocationCatalogServiceDep

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_table_search_service(
    session: SessionDep, locations: LocationCatalogServiceDep, settings: SettingsDep
) -> TableSearchService:
    return TableSearchService(session, locations, settings.booking)


def get_booking_service(
    session: SessionDep, locations: LocationCatalogServiceDep, settings: SettingsDep
) -> BookingService:
    return BookingService(session, locations, settings.booking)


def get_participant_service(
    session: SessionDep, locations: LocationCatalogServiceDep, settings: SettingsDep
) -> ParticipantService:
    return ParticipantService(session, locations, settings.booking)


def get_booking_request_service(
    session: SessionDep, locations: LocationCatalogServiceDep, settings: SettingsDep
) -> BookingRequestService:
    return BookingRequestService(session, locations, settings.booking)


def get_guest_cookies(settings: SettingsDep) -> GuestCookies:
    return GuestCookies(settings.booking)


TableSearchServiceDep = Annotated[TableSearchService, Depends(get_table_search_service)]
BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
ParticipantServiceDep = Annotated[ParticipantService, Depends(get_participant_service)]
BookingRequestServiceDep = Annotated[BookingRequestService, Depends(get_booking_request_service)]
GuestCookiesDep = Annotated[GuestCookies, Depends(get_guest_cookies)]
GuestTokenCookie = Annotated[str | None, Cookie(alias=GuestCookies.NAME)]

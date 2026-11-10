from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.core.locations.services.location_catalog_service import LocationCatalogService

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_location_catalog_service(
    session: SessionDep, settings: SettingsDep
) -> LocationCatalogService:
    return LocationCatalogService(session, public_base_url=settings.media.public_base_url)


LocationCatalogServiceDep = Annotated[LocationCatalogService, Depends(get_location_catalog_service)]

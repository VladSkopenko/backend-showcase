from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import get_session
from app.config.settings import Settings, get_settings
from app.features.menu.services.dish_catalog_service import DishCatalogService

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_dish_catalog_service(session: SessionDep, settings: SettingsDep) -> DishCatalogService:
    return DishCatalogService(session, public_base_url=settings.media.public_base_url)


DishCatalogServiceDep = Annotated[DishCatalogService, Depends(get_dish_catalog_service)]

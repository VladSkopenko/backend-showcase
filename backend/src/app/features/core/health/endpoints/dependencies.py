from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine

from app.common.database import get_engine
from app.config.settings import Settings, get_settings
from app.features.core.health.services.health_service import HealthService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_database_engine() -> AsyncEngine:
    return get_engine()


EngineDep = Annotated[AsyncEngine, Depends(get_database_engine)]


# The probe gets the engine, never the request session: get_session would commit after a failed
# query and turn the 503 into a 500.
def get_health_service(engine: EngineDep, settings: SettingsDep) -> HealthService:
    return HealthService(engine, timeout_seconds=settings.database.probe_timeout_seconds)


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]

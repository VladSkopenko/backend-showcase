from fastapi import APIRouter, Response, status

from app.config.settings import get_settings
from app.features.core.health.endpoints.dependencies import HealthServiceDep
from app.features.core.health.schemas import HealthResponse, RootResponse

router = APIRouter()


@router.get("/", response_model=RootResponse)
def root() -> RootResponse:
    return RootResponse(message=f"{get_settings().app.name} works")


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(health_service: HealthServiceDep, response: Response) -> HealthResponse:
    report = await health_service.check()
    if not report.database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="error", database="unavailable")
    return HealthResponse(status="ok", database="ok")

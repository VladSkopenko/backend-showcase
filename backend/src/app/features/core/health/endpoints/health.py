from fastapi import APIRouter, Response, status

from app.features.core.health.endpoints.dependencies import HealthServiceDep
from app.features.core.health.endpoints.openapi_tags import HealthOpenApiTags
from app.features.core.health.schemas import HealthResponse

router = APIRouter(tags=[HealthOpenApiTags.HEALTH])


@router.get(
    "/health",
    response_model=HealthResponse,
    description=(
        "Checks the database; 503 when it is unreachable. The deploy gate and the container "
        "healthcheck probe it."
    ),
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(health_service: HealthServiceDep, response: Response) -> HealthResponse:
    report = await health_service.check()
    if not report.database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="error", database="unavailable")
    return HealthResponse(status="ok", database="ok")

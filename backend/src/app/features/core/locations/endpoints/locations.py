import uuid

from fastapi import APIRouter

from app.features.core.locations.endpoints.dependencies import LocationCatalogServiceDep
from app.features.core.locations.endpoints.openapi_tags import LocationsOpenApiTags
from app.features.core.locations.schemas import LocationCardResponse, LocationResponse

router = APIRouter(prefix="/locations", tags=[LocationsOpenApiTags.LOCATIONS])


@router.get(
    "",
    response_model=list[LocationCardResponse],
    description=(
        "Lists every location as a card with its number of tables, oldest first; not paginated."
    ),
)
async def list_locations(catalog: LocationCatalogServiceDep) -> list[LocationCardResponse]:
    return [LocationCardResponse.model_validate(view) for view in await catalog.list_all()]


@router.get(
    "/{location_id}",
    response_model=LocationResponse,
    description="Returns one location with its description; 404 if unknown.",
)
async def get_location(
    location_id: uuid.UUID, catalog: LocationCatalogServiceDep
) -> LocationResponse:
    return LocationResponse.model_validate(await catalog.get(location_id=location_id))

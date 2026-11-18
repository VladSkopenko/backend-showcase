from langchain_core.tools import BaseTool, StructuredTool

from app.common.ai_tools import AiToolContext, invalid_arguments, tool_result
from app.features.core.locations.ai_tools.arguments import ListLocationsArguments
from app.features.core.locations.services.location_catalog_service import LocationCatalogService


class LocationTools:
    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    def build(self) -> list[BaseTool]:
        return [
            StructuredTool.from_function(
                coroutine=self._list_locations,
                name="list_locations",
                description=(
                    "Lists the restaurant's locations, the oldest first: id, address, a "
                    "description of the place and the number of tables at each."
                ),
                args_schema=ListLocationsArguments,
                handle_validation_error=invalid_arguments,
            )
        ]

    async def _list_locations(self) -> str:
        async with self._context.sessionmaker() as session:
            locations = await LocationCatalogService(
                session, public_base_url=self._context.public_base_url
            ).list_all()
        return tool_result(
            [
                {
                    "id": str(location.id),
                    "address": location.address,
                    "description": location.description,
                    "table_count": location.table_count,
                }
                for location in locations
            ]
        )

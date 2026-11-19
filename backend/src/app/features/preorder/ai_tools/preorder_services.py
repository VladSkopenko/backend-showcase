from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai_tools import AiToolContext
from app.features.core.bookings.services.participant_service import ParticipantService
from app.features.core.locations.services.location_catalog_service import LocationCatalogService
from app.features.core.menu.services.dish_catalog_service import DishCatalogService
from app.features.preorder.services.preorder_service import PreorderService


class PreorderServices:
    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    def participants(self, session: AsyncSession) -> ParticipantService:
        locations = LocationCatalogService(session, public_base_url=self._context.public_base_url)
        return ParticipantService(session, locations, self._context.booking)

    def preorders(self, session: AsyncSession) -> PreorderService:
        return PreorderService(
            session,
            self.participants(session),
            DishCatalogService(session, public_base_url=self._context.public_base_url),
            max_item_quantity=self._context.max_item_quantity,
            timezone=self._context.booking.timezone,
        )

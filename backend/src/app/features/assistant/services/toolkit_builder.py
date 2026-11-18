from langchain_core.tools import BaseTool

from app.common.ai_tools import AiToolContext
from app.features.core.bookings.ai_tools import BookingTools
from app.features.core.locations.ai_tools import LocationTools
from app.features.core.menu.ai_tools import MenuTools
from app.features.preorder.ai_tools import PreorderTools


class ToolkitBuilder:
    """The composition root of every feature's ai_tools (ADR 20)."""

    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    def build(self) -> list[BaseTool]:
        return [
            *MenuTools(self._context).build(),
            *LocationTools(self._context).build(),
            *BookingTools(self._context).build(),
            *PreorderTools(self._context).build(),
        ]

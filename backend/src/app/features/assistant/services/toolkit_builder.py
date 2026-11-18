from langchain_core.tools import BaseTool

from app.common.ai_tools import AiToolContext
from app.features.core.menu.ai_tools import MenuTools


class ToolkitBuilder:
    """The composition root of every feature's ai_tools (ADR 20)."""

    def __init__(self, context: AiToolContext) -> None:
        self._context = context

    def build(self) -> list[BaseTool]:
        return [*MenuTools(self._context).build()]

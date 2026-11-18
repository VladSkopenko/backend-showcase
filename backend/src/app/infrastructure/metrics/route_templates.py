from collections.abc import Iterable

from fastapi import APIRouter
from fastapi.routing import APIRoute


class RouteTemplates:
    UNMATCHED = "unmatched"

    def __init__(self, routers: Iterable[tuple[APIRouter, str]]) -> None:
        self._templates = {
            id(route): (route, prefix + route.path)
            for router, prefix in routers
            for route in router.routes
            if isinstance(route, APIRoute)
        }

    @property
    def templates(self) -> set[str]:
        return {template for _, template in self._templates.values()}

    def template_of(self, route: object) -> str:
        stored = self._templates.get(id(route))
        if stored is None or stored[0] is not route:
            return self.UNMATCHED
        return stored[1]

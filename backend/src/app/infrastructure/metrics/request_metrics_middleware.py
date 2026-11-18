import time

from prometheus_client import CollectorRegistry, Counter, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.infrastructure.metrics.route_templates import RouteTemplates


class RequestMetricsMiddleware:
    SERVER_ERROR_STATUS = 500
    METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
    OTHER_METHOD = "other"

    def __init__(
        self, app: ASGIApp, *, registry: CollectorRegistry, route_templates: RouteTemplates
    ) -> None:
        self._app = app
        self._route_templates = route_templates
        self._requests = Counter(
            "http_requests_total",
            "HTTP requests by method, route template and status.",
            ["method", "route", "status"],
            registry=registry,
        )
        self._duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds by method and route template.",
            ["method", "route"],
            registry=registry,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # The Exception handler runs outside user middleware: an unhandled error reaches here
        # raw, before any http.response.start, and is counted as the 500 it becomes.
        status = self.SERVER_ERROR_STATUS

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        started = time.perf_counter()
        try:
            await self._app(scope, receive, send_with_status)
        finally:
            method = scope["method"] if scope["method"] in self.METHODS else self.OTHER_METHOD
            route = self._route_templates.template_of(scope.get("route"))
            self._duration.labels(method, route).observe(time.perf_counter() - started)
            self._requests.labels(method, route, str(status)).inc()

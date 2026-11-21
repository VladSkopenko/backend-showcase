import logging

from limits import parse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.common.error_responses import rate_limited_response
from app.infrastructure.rate_limit.rate_limiter import limiter, seconds_until_reset

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    LIMIT = parse("300/minute")
    SCOPE = "all-routes"
    UNKNOWN_CLIENT = "unknown"

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not limiter.enabled:
            await self._app(scope, receive, send)
            return
        scope.setdefault("state", {}).setdefault("view_rate_limit", None)
        client = scope.get("client")
        key = (client[0] if client else self.UNKNOWN_CLIENT, self.SCOPE)
        if self._is_allowed(key):
            await self._app(scope, receive, send)
            return
        response = rate_limited_response(retry_after=seconds_until_reset(self.LIMIT, *key))
        await response(scope, receive, send)

    def _is_allowed(self, key: tuple[str, str]) -> bool:
        try:
            return limiter.limiter.hit(self.LIMIT, *key)
        except Exception:
            logger.exception("Rate limit storage failed; the request is served without a limit")
            return True

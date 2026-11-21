import math
import time

from fastapi import Request
from limits import RateLimitItem
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config.settings import RateLimitSettings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=RateLimitSettings().storage_uri,
    swallow_errors=True,
)


def seconds_until_reset(limit: RateLimitItem, *key: str) -> int:
    reset_at = limiter.limiter.get_window_stats(limit, *key).reset_time
    return max(1, math.ceil(reset_at - time.time()))


def retry_after_seconds(request: Request) -> int:
    limit, key = request.state.view_rate_limit
    return seconds_until_reset(limit, *key)

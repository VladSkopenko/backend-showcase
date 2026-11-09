from app.features.core.auth.endpoints.auth import router
from app.features.core.auth.endpoints.errors import ERROR_STATUSES
from app.features.core.auth.endpoints.oauth import router as oauth_router
from app.features.core.auth.endpoints.openapi_tags import AuthOpenApiTags

__all__ = ["ERROR_STATUSES", "AuthOpenApiTags", "oauth_router", "router"]

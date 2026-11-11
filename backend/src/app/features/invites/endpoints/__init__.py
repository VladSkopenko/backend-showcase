from app.features.invites.endpoints.errors import ERROR_STATUSES
from app.features.invites.endpoints.invites import router
from app.features.invites.endpoints.openapi_tags import InvitesOpenApiTags

__all__ = ["ERROR_STATUSES", "InvitesOpenApiTags", "router"]

from app.config.settings import GoogleSettings
from app.features.core.auth.enums import OAuthProvider
from app.features.core.auth.services.oauth_providers.base import OAuthIdentityProvider
from app.features.core.auth.services.oauth_providers.google import GoogleOAuthProvider


class OAuthProviderRegistry:
    def __init__(self, *, google: GoogleSettings) -> None:
        self._providers: dict[OAuthProvider, OAuthIdentityProvider] = {
            OAuthProvider.GOOGLE: GoogleOAuthProvider(is_configured=google.is_configured),
        }

    def get(self, *, provider: OAuthProvider) -> OAuthIdentityProvider:
        return self._providers[provider]

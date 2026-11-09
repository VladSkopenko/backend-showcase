from collections.abc import Mapping
from typing import Any

from authlib.integrations.starlette_client import OAuth, OAuthError
from starlette.requests import Request
from starlette.responses import Response

from app.config.settings import GoogleSettings
from app.infrastructure.oauth.oauth_exchange_error import OAuthExchangeError


class OAuthClients:
    """Authlib clients for the configured providers; state, nonce and PKCE live in request.session.

    `server` replaces a provider's metadata URL with inline metadata and `client_kwargs` reach the
    httpx2 client (e.g. a transport); both exist so tests run the real flow without a network.
    """

    GOOGLE_SLUG = "google"
    GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"
    SCOPE = "openid email profile"
    CANCELLED_ERROR = "access_denied"

    def __init__(
        self,
        *,
        google: GoogleSettings,
        server: Mapping[str, Mapping[str, Any]] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        self._oauth = OAuth()
        servers = server or {}
        if google.is_configured:
            self._oauth.register(
                name=self.GOOGLE_SLUG,
                client_id=google.client_id,
                client_secret=google.client_secret.get_secret_value(),
                client_kwargs={
                    "scope": self.SCOPE,
                    "code_challenge_method": "S256",
                    **(client_kwargs or {}),
                },
                **servers.get(self.GOOGLE_SLUG, {"server_metadata_url": self.GOOGLE_METADATA_URL}),
            )

    async def authorize_redirect(
        self, *, request: Request, provider_slug: str, redirect_uri: str
    ) -> Response:
        try:
            response: Response = await self._client(provider_slug).authorize_redirect(
                request, redirect_uri
            )
        except Exception as error:
            request.session.clear()
            raise OAuthExchangeError() from error
        return response

    async def fetch_claims(self, *, request: Request, provider_slug: str) -> dict[str, Any]:
        # authlib raises on a provider error before it clears its state data, so the session is
        # emptied here on every exit and the oauth_state cookie is deleted.
        try:
            token = await self._client(provider_slug).authorize_access_token(request)
            userinfo = token.get("userinfo")
            if userinfo is None:
                raise OAuthExchangeError()
        except OAuthError as error:
            raise OAuthExchangeError(cancelled=error.error == self.CANCELLED_ERROR) from error
        except OAuthExchangeError:
            raise
        except Exception as error:
            raise OAuthExchangeError() from error
        finally:
            request.session.clear()
        return dict(userinfo)

    def _client(self, provider_slug: str) -> Any:
        client = self._oauth.create_client(provider_slug)
        if client is None:
            raise OAuthExchangeError()
        return client

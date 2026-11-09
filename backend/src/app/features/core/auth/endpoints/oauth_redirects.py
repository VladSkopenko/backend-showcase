from urllib.parse import urlencode


class OAuthRedirects:
    """Frontend URLs for the OAuth round trip; never built from the request host (AD-19)."""

    ERROR_PARAMETER = "auth_error"
    CALLBACK_ROUTE = "complete_oauth_sign_in"

    def __init__(self, *, frontend_url: str) -> None:
        self._frontend_url = frontend_url.rstrip("/")

    def callback(self, *, path: str) -> str:
        return f"{self._frontend_url}{path}"

    def success(self) -> str:
        return f"{self._frontend_url}/"

    def error(self, *, code: str) -> str:
        return f"{self._frontend_url}/?{urlencode({self.ERROR_PARAMETER: code})}"

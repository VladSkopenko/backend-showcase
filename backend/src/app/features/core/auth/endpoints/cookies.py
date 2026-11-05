from collections.abc import Mapping

from fastapi import Response

from app.config.settings import TokenSettings
from app.features.core.auth.dto import IssuedSession


class SessionCookies:
    """Writes session cookies on the response a handler returns.

    FastAPI drops headers set on an injected Response once a handler returns its own Response, so
    every handler that changes cookies builds its response and passes it here.
    """

    ACCESS_NAME = "access_token"
    REFRESH_NAME = "refresh_token"

    def __init__(self, tokens: TokenSettings, request_cookies: Mapping[str, str]) -> None:
        self._tokens = tokens
        self._request_cookies = request_cookies

    def set(self, *, response: Response, session: IssuedSession) -> None:
        response.set_cookie(
            self.ACCESS_NAME,
            session.access_token,
            max_age=self._tokens.access_ttl_minutes * 60,
            path=self._tokens.access_cookie_path,
            secure=True,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            self.REFRESH_NAME,
            session.refresh_token,
            max_age=self._tokens.refresh_ttl_days * 24 * 60 * 60,
            path=self._tokens.refresh_cookie_path,
            secure=True,
            httponly=True,
            samesite="lax",
        )

    def clear(self, *, response: Response) -> None:
        # Only when a cookie arrived: a cross-site top-level POST carries none (SameSite=Lax) and
        # must not log the user out. delete_cookie defaults to path="/", so every attribute repeats.
        if (
            self.ACCESS_NAME not in self._request_cookies
            and self.REFRESH_NAME not in self._request_cookies
        ):
            return
        response.delete_cookie(
            self.ACCESS_NAME,
            path=self._tokens.access_cookie_path,
            secure=True,
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie(
            self.REFRESH_NAME,
            path=self._tokens.refresh_cookie_path,
            secure=True,
            httponly=True,
            samesite="lax",
        )

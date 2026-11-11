from fastapi import Response

from app.config.settings import BookingSettings


class GuestCookies:
    NAME = "guest_token"

    def __init__(self, settings: BookingSettings) -> None:
        self._settings = settings

    def set(self, *, response: Response, token: str | None) -> None:
        if token is None:
            return
        response.set_cookie(
            self.NAME,
            token,
            max_age=self._settings.guest_token_ttl_days * 24 * 60 * 60,
            path=self._settings.guest_cookie_path,
            secure=True,
            httponly=True,
            samesite="lax",
        )

from collections.abc import Mapping
from typing import Any

from app.features.core.auth.dto import OAuthIdentity
from app.features.core.auth.services.exceptions import OAuthFailedError
from app.features.core.auth.services.oauth_providers.base import OAuthIdentityProvider


class GoogleOAuthProvider(OAuthIdentityProvider):
    def identity(self, *, claims: Mapping[str, Any]) -> OAuthIdentity:
        subject = self._text(claims.get("sub"))
        if subject is None:
            raise OAuthFailedError()
        email = self._text(claims.get("email"))
        first_name = (
            self._text(claims.get("given_name"))
            or self._text(claims.get("name"))
            or (email.split("@", 1)[0] if email is not None else "")
        )
        return OAuthIdentity(
            subject=subject,
            email=email,
            email_verified=self._flag(claims.get("email_verified")),
            first_name=self._name(first_name),
            last_name=self._name(self._text(claims.get("family_name")) or ""),
        )

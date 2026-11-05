import uuid
from datetime import timedelta

import jwt

from app.common import clock
from app.features.core.auth.services.exceptions import NotAuthenticatedError


class AccessTokenCodec:
    def __init__(self, *, secret_key: str, algorithm: str, ttl_minutes: int) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._ttl = timedelta(minutes=ttl_minutes)

    def encode(self, *, user_id: uuid.UUID) -> str:
        issued_at = clock.now()
        claims = {
            "sub": str(user_id),
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + self._ttl).timestamp()),
        }
        return jwt.encode(claims, self._secret_key, algorithm=self._algorithm)

    def decode(self, *, token: str) -> uuid.UUID:
        try:
            # PyJWT checks exp and iat against the real clock; expiry is checked below against
            # app.common.clock instead, so tests can move time.
            claims = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                options={
                    "verify_exp": False,
                    "verify_iat": False,
                    "require": ["sub", "iat", "exp"],
                },
            )
        except jwt.PyJWTError as exc:
            raise NotAuthenticatedError() from exc
        expires_at = claims["exp"]
        if type(expires_at) is not int or expires_at <= clock.now().timestamp():
            raise NotAuthenticatedError()
        try:
            return uuid.UUID(claims["sub"])
        except ValueError as exc:
            raise NotAuthenticatedError() from exc

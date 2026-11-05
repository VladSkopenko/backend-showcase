from dataclasses import dataclass


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str

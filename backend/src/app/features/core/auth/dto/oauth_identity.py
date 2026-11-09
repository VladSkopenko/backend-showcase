from dataclasses import dataclass


@dataclass(frozen=True)
class OAuthIdentity:
    subject: str
    email: str | None
    email_verified: bool
    first_name: str
    last_name: str

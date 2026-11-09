from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from app.features.core.auth.dto import OAuthIdentity


class OAuthIdentityProvider(ABC):
    NAME_MAX_LENGTH = 100

    def __init__(self, *, is_configured: bool) -> None:
        self.is_configured = is_configured

    @abstractmethod
    def identity(self, *, claims: Mapping[str, Any]) -> OAuthIdentity: ...

    def _flag(self, value: Any) -> bool:
        return value is True or value == "true"

    def _text(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _name(self, value: str) -> str:
        return value[: self.NAME_MAX_LENGTH]

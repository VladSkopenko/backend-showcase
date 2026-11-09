import enum


class OAuthProvider(enum.Enum):
    GOOGLE = "GOOGLE"

    @property
    def slug(self) -> str:
        return self.value.lower()

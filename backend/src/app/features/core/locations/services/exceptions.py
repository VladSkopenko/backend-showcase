from app.common.errors import DomainError


class LocationNotFoundError(DomainError):
    def __init__(self) -> None:
        super().__init__("LOCATION_NOT_FOUND", "No location with this id exists.")


class LocationPhotoSeedError(DomainError):
    def __init__(self, slugs: list[str]) -> None:
        super().__init__(
            "LOCATION_PHOTOS_MISSING", f"Photos are missing for locations: {', '.join(slugs)}"
        )

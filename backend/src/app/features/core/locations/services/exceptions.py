from app.common.errors import DomainError


class LocationNotFoundError(DomainError):
    code = "LOCATION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No location with this id exists.")


class LocationPhotoSeedError(DomainError):
    code = "LOCATION_PHOTOS_MISSING"

    def __init__(self, slugs: list[str]) -> None:
        super().__init__(f"Photos are missing for locations: {', '.join(slugs)}")

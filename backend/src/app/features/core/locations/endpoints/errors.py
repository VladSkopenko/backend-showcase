from fastapi import status

from app.common.errors import DomainError
from app.features.core.locations.services.exceptions import LocationNotFoundError

ERROR_STATUSES: dict[type[DomainError], int] = {
    LocationNotFoundError: status.HTTP_404_NOT_FOUND,
}

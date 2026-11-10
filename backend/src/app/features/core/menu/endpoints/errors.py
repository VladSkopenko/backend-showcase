from fastapi import status

from app.common.errors import DomainError
from app.features.core.menu.services.exceptions import DishNotFoundError

ERROR_STATUSES: dict[type[DomainError], int] = {
    DishNotFoundError: status.HTTP_404_NOT_FOUND,
}

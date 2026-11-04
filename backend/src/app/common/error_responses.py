from collections.abc import Mapping

from fastapi import status
from fastapi.responses import JSONResponse

from app.common.errors import DomainError


def domain_error_response(
    error: DomainError, statuses: Mapping[type[DomainError], int]
) -> JSONResponse:
    status_code = next(
        (statuses[cls] for cls in type(error).__mro__ if cls in statuses),
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
    body: dict[str, str | int] = {"code": error.code, "message": error.message}
    headers: dict[str, str] | None = None
    if error.retry_after is not None:
        body["retry_after"] = error.retry_after
        headers = {"Retry-After": str(error.retry_after)}
    return JSONResponse(body, status_code=status_code, headers=headers)

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.common.errors import DomainError

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    retry_after: int | None = None
    details: list[ErrorDetail] | None = None


class ErrorCodes:
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    HTTP_ERROR = "HTTP_ERROR"
    SERVER_ERROR = "SERVER_ERROR"


class ErrorMessages:
    SERVER_ERROR = "Something went wrong."
    HTTP_LAYER = {
        status.HTTP_404_NOT_FOUND: (ErrorCodes.NOT_FOUND, "Not found."),
        status.HTTP_405_METHOD_NOT_ALLOWED: (ErrorCodes.METHOD_NOT_ALLOWED, "Method not allowed."),
    }
    INVALID_JSON = "Request body is not valid JSON."
    MISSING_BODY = "Request body is required."
    BODY_NOT_OBJECT = "Request body must be a JSON object."
    INVALID_EMAIL = "Enter a valid email address."
    INVALID_VALUE = "Is invalid."
    BY_VALIDATION_TYPE = {
        "missing": "This field is required.",
        "string_too_short": "Must be at least {min_length} characters.",
        "string_too_long": "Must be at most {max_length} characters.",
        "string_pattern_mismatch": "Has an invalid format.",
        "less_than_equal": "Must be at most {le}.",
        "greater_than_equal": "Must be at least {ge}.",
        "enum": "Has an invalid value.",
        "uuid_parsing": "Has an invalid format.",
        "int_parsing": "Has an invalid format.",
    }


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    retry_after: int | None = None,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, retry_after=retry_after, details=details)
    response_headers = dict(headers or {})
    if retry_after is not None:
        response_headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=status_code,
        headers=response_headers or None,
    )


def server_error_response() -> JSONResponse:
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ErrorCodes.SERVER_ERROR,
        message=ErrorMessages.SERVER_ERROR,
    )


def domain_error_response(
    error: DomainError, statuses: Mapping[type[DomainError], int]
) -> JSONResponse:
    status_code = _status_of(type(error), statuses)
    if status_code is None:
        # Often returned rather than raised, so the error is passed explicitly as exc_info.
        logger.error("Domain error %s has no HTTP status", error.code, exc_info=error)
        return server_error_response()
    return error_response(
        status_code=status_code,
        code=error.code,
        message=error.message,
        retry_after=error.retry_after,
    )


def http_error_response(error: HTTPException) -> JSONResponse:
    if error.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
        return server_error_response()
    code, message = ErrorMessages.HTTP_LAYER.get(
        error.status_code,
        (ErrorCodes.HTTP_ERROR, f"{HTTPStatus(error.status_code).phrase}."),
    )
    return error_response(
        status_code=error.status_code, code=code, message=message, headers=error.headers
    )


def validation_error_response(error: RequestValidationError) -> JSONResponse:
    details = [_validation_detail(item) for item in error.errors()]
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code=ErrorCodes.VALIDATION_ERROR,
        message=details[0].message,
        details=details,
    )


def _validation_detail(error: Mapping[str, Any]) -> ErrorDetail:
    error_type: str = error["type"]
    loc = tuple(error["loc"])
    # Checked before loc: a JSON decode error carries a character offset in loc.
    if error_type == "json_invalid":
        return ErrorDetail(message=ErrorMessages.INVALID_JSON)
    if loc == ("body",):
        if error_type == "missing":
            return ErrorDetail(message=ErrorMessages.MISSING_BODY)
        if error_type in ("model_attributes_type", "dict_type"):
            return ErrorDetail(message=ErrorMessages.BODY_NOT_OBJECT)
        return ErrorDetail(message=_validation_message(error_type, error.get("ctx", {})))
    return ErrorDetail(
        field=".".join(str(part) for part in loc[1:]) or None,
        message=_validation_message(error_type, error.get("ctx", {})),
    )


def _validation_message(error_type: str, ctx: Mapping[str, Any]) -> str:
    if error_type == "value_error":
        # Own validators put their ValueError in ctx["error"]; EmailStr sets ctx["reason"].
        if "error" in ctx:
            return str(ctx["error"])
        return ErrorMessages.INVALID_EMAIL if "reason" in ctx else ErrorMessages.INVALID_VALUE
    if error_type == "string_too_short" and ctx.get("min_length") == 1:
        return ErrorMessages.BY_VALIDATION_TYPE["missing"]
    template = ErrorMessages.BY_VALIDATION_TYPE.get(error_type, ErrorMessages.INVALID_VALUE)
    return template.format_map(ctx)


def error_responses(
    *errors: type[DomainError],
    statuses: Mapping[type[DomainError], int] | None = None,
    http_errors: Mapping[int, str] | None = None,
    takes_input: bool,
) -> dict[int | str, dict[str, Any]]:
    documented: dict[int, list[str]] = {}
    for error in errors:
        status_code = _status_of(error, statuses or {})
        if status_code is None:
            raise ValueError(f"{error.__name__} has no HTTP status in the error map")
        documented.setdefault(status_code, []).append(error.code)
    for status_code, code in (http_errors or {}).items():
        documented.setdefault(status_code, []).append(code)
    if takes_input:
        documented[status.HTTP_422_UNPROCESSABLE_CONTENT] = [ErrorCodes.VALIDATION_ERROR]
    return {
        status_code: {
            "model": ErrorResponse,
            "description": (
                f"{HTTPStatus(status_code).phrase}. Codes: "
                f"{', '.join(f'`{code}`' for code in codes)}."
            ),
        }
        for status_code, codes in sorted(documented.items())
    }


def _status_of(error: type[DomainError], statuses: Mapping[type[DomainError], int]) -> int | None:
    return next((statuses[cls] for cls in error.__mro__ if cls in statuses), None)

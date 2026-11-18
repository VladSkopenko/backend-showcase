"""What every feature's ai_tools package shares; imports nothing from features (ADR 20)."""

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import BookingSettings

if TYPE_CHECKING:
    from pydantic.v1 import ValidationError as ValidationErrorV1


@dataclass(frozen=True)
class AiToolContext:
    """Bound per request: the user comes from the JWT, never from a tool argument."""

    user_id: uuid.UUID
    sessionmaker: async_sessionmaker[AsyncSession]
    public_base_url: str
    booking: BookingSettings
    max_item_quantity: int


class AiToolErrors:
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    MALFORMED_CALL = "MALFORMED_CALL"
    TOOL_FAILED = "TOOL_FAILED"


TRUNCATION_MARKER = " …[truncated]"


def tool_result(payload: Any) -> str:
    return json.dumps(payload)


def usd(cents: int) -> str:
    return f"{Decimal(cents).scaleb(-2):f}"


def tool_error(code: str, message: str | None = None) -> str:
    payload: dict[str, str] = {"error": code}
    if message is not None:
        payload["message"] = message
    return tool_result(payload)


def invalid_arguments(error: ValidationError | ValidationErrorV1) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    )
    return tool_error(AiToolErrors.INVALID_ARGUMENTS, problems)


def cut_tool_result(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + TRUNCATION_MARKER

"""What every feature's ai_tools package shares; imports nothing from features (ADR 20)."""

import json
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import BookingSettings

if TYPE_CHECKING:
    from pydantic.v1 import ValidationError as ValidationErrorV1


@dataclass(frozen=True)
class CardField:
    label: str
    value: str


@dataclass(frozen=True)
class Card:
    """What the guest confirms; English only, the same shape for every action."""

    title: str
    fields: list[CardField]
    notice: str | None
    confirm_label: str


@dataclass(frozen=True)
class Proposal:
    """A write a tool checked and the guest still has to confirm: pinned values and the card."""

    kind: str
    payload: dict[str, Any]
    card: Card


class ProposalSink:
    """Holds the one proposal of a turn; the turn stores it with the assistant message."""

    def __init__(self) -> None:
        self.proposal: Proposal | None = None

    @property
    def is_full(self) -> bool:
        return self.proposal is not None

    def hold(self, proposal: Proposal) -> None:
        if self.proposal is not None:
            raise RuntimeError("A turn holds one proposal")
        self.proposal = proposal


@dataclass(frozen=True)
class AiToolContext:
    """Bound per request: the user comes from the JWT, never from a tool argument."""

    user_id: uuid.UUID
    sessionmaker: async_sessionmaker[AsyncSession]
    public_base_url: str
    booking: BookingSettings
    max_item_quantity: int
    proposals: ProposalSink = field(default_factory=ProposalSink)


@dataclass(frozen=True)
class ActionContext:
    """What an applier gets: the caller's session, so the claim and the write commit together."""

    session: AsyncSession
    user_id: uuid.UUID
    payload: Mapping[str, Any]


class ActionApplier(Protocol):
    async def apply(self, context: ActionContext) -> dict[str, Any]: ...


@asynccontextmanager
async def dry_run(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """A session whose work is always rolled back, so a proposal runs the real checks and writes
    nothing."""
    async with sessionmaker() as session:
        try:
            yield session
        finally:
            await session.rollback()


class AiToolErrors:
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    MALFORMED_CALL = "MALFORMED_CALL"
    TOOL_FAILED = "TOOL_FAILED"
    ONE_PROPOSAL_PER_TURN = "ONE_PROPOSAL_PER_TURN"


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

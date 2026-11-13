import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ItemNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class SetCartItemRequest(BaseModel):
    quantity: Annotated[int, Field(ge=1)]
    note: ItemNote | None = None


class CartDishResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    price_cents: int
    image_url: str
    is_available: bool
    prep_minutes: int


class CartLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dish: CartDishResponse
    quantity: int
    note: str | None
    line_total_cents: int


class CartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[CartLineResponse]
    total_cents: int


class SubmittedPartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    submitted_at: datetime
    items: list[CartLineResponse]
    total_cents: int


class MyPreorderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parts: list[SubmittedPartResponse]
    total_cents: int

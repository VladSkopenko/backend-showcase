import uuid
from dataclasses import dataclass
from datetime import datetime

from app.features.preorder.dto.cart_line_view import CartLineView


@dataclass(frozen=True)
class SubmittedPartView:
    id: uuid.UUID
    submitted_at: datetime
    items: list[CartLineView]
    total_cents: int

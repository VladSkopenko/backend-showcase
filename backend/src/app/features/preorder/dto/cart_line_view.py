import uuid
from dataclasses import dataclass

from app.features.core.menu.dto import DishView


@dataclass(frozen=True)
class CartLineView:
    id: uuid.UUID
    dish: DishView
    quantity: int
    note: str | None
    line_total_cents: int

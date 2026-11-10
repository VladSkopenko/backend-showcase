from dataclasses import dataclass

from app.features.core.menu.dto.dish_view import DishView


@dataclass(frozen=True)
class DishPage:
    items: list[DishView]
    total: int
    limit: int
    offset: int

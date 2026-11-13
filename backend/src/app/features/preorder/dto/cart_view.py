from dataclasses import dataclass

from app.features.preorder.dto.cart_line_view import CartLineView


@dataclass(frozen=True)
class CartView:
    items: list[CartLineView]
    total_cents: int

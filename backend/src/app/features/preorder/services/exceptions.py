from app.common.errors import DomainError


class PreorderClosedError(DomainError):
    code = "PREORDER_CLOSED"

    def __init__(self) -> None:
        super().__init__("Pre-order is closed: the booking was cancelled or starts soon.")


class QuantityTooLargeError(DomainError):
    code = "QUANTITY_TOO_LARGE"

    def __init__(self) -> None:
        super().__init__("This many portions of one dish cannot be pre-ordered online.")


class DishUnavailableError(DomainError):
    code = "DISH_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("This dish is not available right now.")


class CartItemNotFoundError(DomainError):
    code = "CART_ITEM_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("This dish is not in your cart.")


class CartEmptyError(DomainError):
    code = "CART_EMPTY"

    def __init__(self) -> None:
        super().__init__("Add a dish to your cart before submitting it.")

from app.common.errors import DomainError


class DishNotFoundError(DomainError):
    code = "DISH_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("No dish with this id exists.")


class MenuSeedFileError(DomainError):
    code = "MENU_SEED_FILE_INVALID"

    def __init__(self, detail: str) -> None:
        super().__init__(f"The menu seed is invalid: {detail}")

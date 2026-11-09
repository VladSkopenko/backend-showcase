from app.common.errors import DomainError


class DishNotFoundError(DomainError):
    def __init__(self) -> None:
        super().__init__("DISH_NOT_FOUND", "No dish with this id exists.")


class MenuSeedFileError(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__("MENU_SEED_FILE_INVALID", f"The menu seed is invalid: {detail}")

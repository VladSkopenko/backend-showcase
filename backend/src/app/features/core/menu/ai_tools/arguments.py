import uuid

from pydantic import BaseModel, Field

from app.features.core.menu.enums import DishCategory


class ListMenuArguments(BaseModel):
    category: DishCategory | None = Field(
        default=None,
        description=(
            "Only dishes of this category: APPETIZER, MAIN_COURSE or DESSERT. Omit for the "
            "whole menu."
        ),
    )


class GetDishArguments(BaseModel):
    dish_id: uuid.UUID = Field(description="The id of the dish, as list_menu returns it.")

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.database import Base
from app.features.core.menu.enums import DishCategory


class Dish(Base):
    __tablename__ = "dishes"
    __table_args__ = (
        CheckConstraint("price_cents > 0", name="price_cents_positive"),
        CheckConstraint("weight_grams > 0", name="weight_grams_positive"),
        CheckConstraint("calories >= 0", name="calories_non_negative"),
        CheckConstraint("popularity >= 0", name="popularity_non_negative"),
        CheckConstraint("prep_minutes > 0", name="prep_minutes_positive"),
        # Named explicitly: the ix naming convention would name it after the first column only.
        Index("ix_dishes_category_popularity", "category", "popularity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[DishCategory] = mapped_column(Enum(DishCategory, name="dish_category"))
    price_cents: Mapped[int] = mapped_column(index=True)
    weight_grams: Mapped[int]
    calories: Mapped[int]
    protein: Mapped[str] = mapped_column(String(50))
    fats: Mapped[str] = mapped_column(String(50))
    carbs: Mapped[str] = mapped_column(String(50))
    vitamins: Mapped[str] = mapped_column(Text)
    is_available: Mapped[bool]
    popularity: Mapped[int] = mapped_column(server_default=text("0"), index=True)
    prep_minutes: Mapped[int]
    image_key: Mapped[str] = mapped_column(String(300))
    # No server default: the seed spreads created_at by file position via app.common.clock.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

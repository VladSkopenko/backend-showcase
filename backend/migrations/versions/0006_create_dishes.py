"""create dishes

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dishes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        # create_table also creates the enum type.
        sa.Column(
            "category",
            sa.Enum("APPETIZER", "MAIN_COURSE", "DESSERT", name="dish_category"),
            nullable=False,
        ),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("weight_grams", sa.Integer(), nullable=False),
        sa.Column("calories", sa.Integer(), nullable=False),
        sa.Column("protein", sa.String(length=50), nullable=False),
        sa.Column("fats", sa.String(length=50), nullable=False),
        sa.Column("carbs", sa.String(length=50), nullable=False),
        sa.Column("vitamins", sa.Text(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("popularity", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("image_key", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("price_cents > 0", name=op.f("ck_dishes_price_cents_positive")),
        sa.CheckConstraint("weight_grams > 0", name=op.f("ck_dishes_weight_grams_positive")),
        sa.CheckConstraint("calories >= 0", name=op.f("ck_dishes_calories_non_negative")),
        sa.CheckConstraint("popularity >= 0", name=op.f("ck_dishes_popularity_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dishes")),
        sa.UniqueConstraint("slug", name=op.f("uq_dishes_slug")),
    )
    op.create_index(
        "ix_dishes_category_popularity", "dishes", ["category", "popularity"], unique=False
    )
    op.create_index(op.f("ix_dishes_created_at"), "dishes", ["created_at"], unique=False)
    op.create_index(op.f("ix_dishes_popularity"), "dishes", ["popularity"], unique=False)
    op.create_index(op.f("ix_dishes_price_cents"), "dishes", ["price_cents"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dishes_price_cents"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_popularity"), table_name="dishes")
    op.drop_index(op.f("ix_dishes_created_at"), table_name="dishes")
    op.drop_index("ix_dishes_category_popularity", table_name="dishes")
    op.drop_table("dishes")
    # drop_table leaves the type behind, and the next upgrade would fail to create it again.
    sa.Enum(name="dish_category").drop(op.get_bind())

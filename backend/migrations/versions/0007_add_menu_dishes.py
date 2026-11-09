"""add menu dishes

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09 00:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Deploys cannot run the seed script (no human path to the server, ADR 2), so the menu ships as
# data. The pictures are already in the bucket under dishes/<slug>.jpg.
NEWEST = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

DISHES = [
    {
        "slug": "pkhali-trio",
        "name": "Pkhali Trio",
        "description": (
            "Spinach, beetroot and leek pkhali with walnuts, garlic, coriander and "
            "pomegranate seeds."
        ),
        "category": "APPETIZER",
        "price_cents": 1100,
        "weight_grams": 240,
        "calories": 320,
        "protein": "9-11g",
        "fats": "22-24g",
        "carbs": "18-20g",
        "vitamins": "Vit A, Vit K, Folate, Iron",
        "is_available": True,
        "popularity": 41,
    },
    {
        "slug": "badrijani-walnut-rolls",
        "name": "Badrijani Walnut Rolls",
        "description": (
            "Fried eggplant rolled with walnut, garlic and blue fenugreek paste, topped with "
            "pomegranate and cilantro."
        ),
        "category": "APPETIZER",
        "price_cents": 1200,
        "weight_grams": 260,
        "calories": 410,
        "protein": "10-12g",
        "fats": "32-35g",
        "carbs": "20-22g",
        "vitamins": "Vit E, Vit B6, Magnesium",
        "is_available": True,
        "popularity": 88,
    },
    {
        "slug": "beetroot-carpaccio",
        "name": "Beetroot Carpaccio with Goat Cheese",
        "description": (
            "Thin slices of roasted beetroot with goat cheese, toasted walnuts, arugula and a"
            " honey drizzle."
        ),
        "category": "APPETIZER",
        "price_cents": 1300,
        "weight_grams": 230,
        "calories": 290,
        "protein": "11-13g",
        "fats": "18-20g",
        "carbs": "19-22g",
        "vitamins": "Vit C, Folate, Calcium",
        "is_available": True,
        "popularity": 34,
    },
    {
        "slug": "red-lentil-soup",
        "name": "Red Lentil Soup",
        "description": (
            "Creamy red lentil soup with cumin, a swirl of yogurt, chili oil and fresh herbs."
        ),
        "category": "APPETIZER",
        "price_cents": 900,
        "weight_grams": 350,
        "calories": 310,
        "protein": "15-17g",
        "fats": "9-11g",
        "carbs": "40-44g",
        "vitamins": "Iron, Folate, Vit B1",
        "is_available": True,
        "popularity": 57,
    },
    {
        "slug": "fresh-strawberry-mint-salad",
        "name": "Fresh Strawberry Mint Salad",
        "description": (
            "Strawberries, spinach, mint leaves, feta or goat cheese, walnuts, balsamic "
            "glaze, poppy seeds."
        ),
        "category": "APPETIZER",
        "price_cents": 1700,
        "weight_grams": 430,
        "calories": 503,
        "protein": "18-20g",
        "fats": "33-35g",
        "carbs": "30-35g",
        "vitamins": "Vit C, Vit A, Calcium, and Ferrum",
        "is_available": True,
        "popularity": 120,
    },
    {
        "slug": "green-asparagus-salad",
        "name": "Green Asparagus Salad",
        "description": (
            "Blanched green asparagus and peas with parmesan shavings, lemon dressing and "
            "fresh herbs."
        ),
        "category": "APPETIZER",
        "price_cents": 1200,
        "weight_grams": 270,
        "calories": 240,
        "protein": "9-11g",
        "fats": "15-17g",
        "carbs": "14-16g",
        "vitamins": "Vit K, Folate, Vit C",
        "is_available": False,
        "popularity": 65,
    },
    {
        "slug": "spring-salad",
        "name": "Spring Salad",
        "description": (
            "Tomatoes, cucumbers, radish, greens and toasted seeds with a light herb vinaigrette."
        ),
        "category": "APPETIZER",
        "price_cents": 1900,
        "weight_grams": 280,
        "calories": 260,
        "protein": "7-9g",
        "fats": "16-18g",
        "carbs": "20-22g",
        "vitamins": "Vit C, Vit A, Potassium",
        "is_available": True,
        "popularity": 73,
    },
    {
        "slug": "citrus-fig-salad",
        "name": "Citrus Fig & Blue Cheese Salad",
        "description": (
            "Grapefruit, orange and fresh figs with blue cheese, walnuts, red chicory and "
            "microgreens."
        ),
        "category": "APPETIZER",
        "price_cents": 1500,
        "weight_grams": 320,
        "calories": 380,
        "protein": "10-12g",
        "fats": "24-26g",
        "carbs": "30-33g",
        "vitamins": "Vit C, Calcium, Potassium",
        "is_available": True,
        "popularity": 96,
    },
    {
        "slug": "avocado-pine-nut-bowl",
        "name": "Avocado Pine Nut Bowl",
        "description": (
            "Avocado, roasted sweet potato, mixed greens, pine nuts and pomegranate with a "
            "lemon-tahini dressing."
        ),
        "category": "APPETIZER",
        "price_cents": 1700,
        "weight_grams": 430,
        "calories": 520,
        "protein": "12-14g",
        "fats": "38-41g",
        "carbs": "28-31g",
        "vitamins": "Vit E, Vit K, Potassium",
        "is_available": True,
        "popularity": 110,
    },
    {
        "slug": "avocado-egg-toast",
        "name": "Avocado Egg Toast",
        "description": (
            "Sourdough toast with smashed avocado, soft-boiled eggs, spinach and chili flakes."
        ),
        "category": "APPETIZER",
        "price_cents": 1000,
        "weight_grams": 220,
        "calories": 390,
        "protein": "16-18g",
        "fats": "24-26g",
        "carbs": "26-28g",
        "vitamins": "Vit B12, Vit D, Vit E",
        "is_available": True,
        "popularity": 82,
    },
    {
        "slug": "grilled-salmon-quinoa",
        "name": "Grilled Salmon with Quinoa",
        "description": (
            "Grilled salmon fillet on herbed quinoa with roasted cherry tomatoes, green beans"
            " and lemon."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 2400,
        "weight_grams": 380,
        "calories": 610,
        "protein": "38-41g",
        "fats": "26-28g",
        "carbs": "45-48g",
        "vitamins": "Vit D, Omega-3, Vit B12",
        "is_available": True,
        "popularity": 104,
    },
    {
        "slug": "chicken-chkmeruli",
        "name": "Chicken Chkmeruli",
        "description": (
            "Roasted chicken baked in a creamy garlic and milk sauce, served in a clay ketsi pan."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 2100,
        "weight_grams": 400,
        "calories": 690,
        "protein": "44-47g",
        "fats": "40-43g",
        "carbs": "12-14g",
        "vitamins": "Vit B6, Niacin, Selenium",
        "is_available": True,
        "popularity": 131,
    },
    {
        "slug": "vegan-ajapsandali",
        "name": "Vegan Ajapsandali",
        "description": (
            "Slow-stewed eggplant, bell peppers, tomatoes and potatoes with basil, coriander "
            "and garlic."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 1600,
        "weight_grams": 380,
        "calories": 330,
        "protein": "7-9g",
        "fats": "16-18g",
        "carbs": "36-39g",
        "vitamins": "Vit C, Vit A, Potassium",
        "is_available": True,
        "popularity": 58,
    },
    {
        "slug": "lobio-with-mchadi",
        "name": "Lobio with Mchadi",
        "description": (
            "Red kidney bean stew with walnuts and herbs, served with cornbread and pickled "
            "vegetables."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 1500,
        "weight_grams": 420,
        "calories": 560,
        "protein": "24-26g",
        "fats": "16-18g",
        "carbs": "74-78g",
        "vitamins": "Iron, Folate, Magnesium",
        "is_available": True,
        "popularity": 77,
    },
    {
        "slug": "mushroom-khinkali",
        "name": "Mushroom Khinkali",
        "description": (
            "Six hand-pleated dumplings filled with mushrooms, onion and herbs, finished with"
            " black pepper."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 1700,
        "weight_grams": 360,
        "calories": 520,
        "protein": "16-18g",
        "fats": "12-14g",
        "carbs": "82-86g",
        "vitamins": "Vit B2, Vit D, Selenium",
        "is_available": True,
        "popularity": 99,
    },
    {
        "slug": "stuffed-bell-peppers",
        "name": "Stuffed Bell Peppers",
        "description": (
            "Bell peppers stuffed with rice, lentils and herbs, baked in tomato sauce with "
            "garlic yogurt."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 1800,
        "weight_grams": 420,
        "calories": 480,
        "protein": "17-19g",
        "fats": "14-16g",
        "carbs": "66-70g",
        "vitamins": "Vit C, Vit A, Fiber",
        "is_available": True,
        "popularity": 46,
    },
    {
        "slug": "grilled-vegetable-skewers",
        "name": "Grilled Vegetable Skewers",
        "description": (
            "Zucchini, mushrooms, bell peppers and red onion from the grill, with green "
            "tkemali plum sauce."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 1600,
        "weight_grams": 350,
        "calories": 300,
        "protein": "8-10g",
        "fats": "14-16g",
        "carbs": "34-37g",
        "vitamins": "Vit C, Vit B6, Potassium",
        "is_available": True,
        "popularity": 38,
    },
    {
        "slug": "mushroom-barley-risotto",
        "name": "Mushroom Barley Risotto",
        "description": "Pearl barley cooked risotto-style with wild mushrooms, parmesan and thyme.",
        "category": "MAIN_COURSE",
        "price_cents": 1900,
        "weight_grams": 380,
        "calories": 540,
        "protein": "16-18g",
        "fats": "18-20g",
        "carbs": "72-76g",
        "vitamins": "Vit B3, Selenium, Fiber",
        "is_available": True,
        "popularity": 62,
    },
    {
        "slug": "spinach-feta-khachapuri",
        "name": "Spinach & Feta Khachapuri",
        "description": "Golden flatbread filled with spinach, feta and sulguni, cut into wedges.",
        "category": "MAIN_COURSE",
        "price_cents": 1800,
        "weight_grams": 400,
        "calories": 780,
        "protein": "30-33g",
        "fats": "34-37g",
        "carbs": "84-88g",
        "vitamins": "Calcium, Vit A, Folate",
        "is_available": True,
        "popularity": 118,
    },
    {
        "slug": "chickpea-buddha-bowl",
        "name": "Chickpea Buddha Bowl",
        "description": (
            "Roasted chickpeas, quinoa, avocado, cucumber, tomatoes and pickled cabbage with "
            "a yogurt dressing."
        ),
        "category": "MAIN_COURSE",
        "price_cents": 1900,
        "weight_grams": 450,
        "calories": 610,
        "protein": "22-24g",
        "fats": "26-28g",
        "carbs": "68-72g",
        "vitamins": "Vit A, Vit E, Iron",
        "is_available": True,
        "popularity": 91,
    },
    {
        "slug": "churchkhela-with-fruit",
        "name": "Churchkhela with Fresh Fruit",
        "description": (
            "Walnut churchkhela in thickened grape juice, served with fresh grapes and figs."
        ),
        "category": "DESSERT",
        "price_cents": 900,
        "weight_grams": 200,
        "calories": 420,
        "protein": "7-9g",
        "fats": "16-18g",
        "carbs": "62-66g",
        "vitamins": "Vit E, Potassium, Iron",
        "is_available": True,
        "popularity": 44,
    },
    {
        "slug": "pelamushi-grape-pudding",
        "name": "Pelamushi Grape Pudding",
        "description": (
            "Traditional grape-juice pudding topped with crushed walnuts and pomegranate seeds."
        ),
        "category": "DESSERT",
        "price_cents": 800,
        "weight_grams": 220,
        "calories": 310,
        "protein": "4-6g",
        "fats": "8-10g",
        "carbs": "54-58g",
        "vitamins": "Vit C, Vit K, Antioxidants",
        "is_available": True,
        "popularity": 29,
    },
    {
        "slug": "mango-chia-pudding",
        "name": "Mango Chia Pudding",
        "description": (
            "Coconut chia pudding layered with mango purée, fresh mango, mint and toasted coconut."
        ),
        "category": "DESSERT",
        "price_cents": 1000,
        "weight_grams": 250,
        "calories": 340,
        "protein": "7-9g",
        "fats": "16-18g",
        "carbs": "40-43g",
        "vitamins": "Vit C, Vit A, Omega-3",
        "is_available": True,
        "popularity": 67,
    },
    {
        "slug": "baked-apples-walnut-honey",
        "name": "Baked Apples with Walnuts",
        "description": (
            "Two baked apples stuffed with walnuts, raisins and cinnamon, drizzled with honey."
        ),
        "category": "DESSERT",
        "price_cents": 900,
        "weight_grams": 260,
        "calories": 330,
        "protein": "4-6g",
        "fats": "12-14g",
        "carbs": "52-56g",
        "vitamins": "Vit C, Fiber, Potassium",
        "is_available": True,
        "popularity": 36,
    },
    {
        "slug": "berry-yogurt-parfait",
        "name": "Berry Yogurt Parfait",
        "description": "Greek yogurt layered with granola, blueberries, raspberries and honey.",
        "category": "DESSERT",
        "price_cents": 1000,
        "weight_grams": 280,
        "calories": 360,
        "protein": "14-16g",
        "fats": "10-12g",
        "carbs": "50-54g",
        "vitamins": "Vit C, Calcium, Vit B12",
        "is_available": True,
        "popularity": 75,
    },
    {
        "slug": "raspberry-cashew-cheesecake",
        "name": "Raspberry Cashew Cheesecake",
        "description": (
            "Vegan cashew cheesecake on a date and nut crust, topped with fresh raspberries."
        ),
        "category": "DESSERT",
        "price_cents": 1200,
        "weight_grams": 160,
        "calories": 440,
        "protein": "9-11g",
        "fats": "30-33g",
        "carbs": "32-35g",
        "vitamins": "Vit E, Magnesium, Vit C",
        "is_available": True,
        "popularity": 83,
    },
    {
        "slug": "lemon-basil-sorbet",
        "name": "Lemon Basil Sorbet",
        "description": "Three scoops of lemon sorbet with fresh basil and lemon zest.",
        "category": "DESSERT",
        "price_cents": 800,
        "weight_grams": 180,
        "calories": 190,
        "protein": "0-1g",
        "fats": "0-1g",
        "carbs": "46-49g",
        "vitamins": "Vit C",
        "is_available": True,
        "popularity": 31,
    },
    {
        "slug": "saperavi-poached-pears",
        "name": "Saperavi Poached Pears",
        "description": (
            "Pears poached in Saperavi red wine with cinnamon and star anise, in their own syrup."
        ),
        "category": "DESSERT",
        "price_cents": 1100,
        "weight_grams": 300,
        "calories": 280,
        "protein": "1-2g",
        "fats": "0-1g",
        "carbs": "62-66g",
        "vitamins": "Vit C, Fiber, Antioxidants",
        "is_available": True,
        "popularity": 48,
    },
    {
        "slug": "citrus-tartlets",
        "name": "Citrus Tartlets",
        "description": "Shortcrust tartlets with vanilla cream, orange slices and blackberries.",
        "category": "DESSERT",
        "price_cents": 1100,
        "weight_grams": 180,
        "calories": 450,
        "protein": "6-8g",
        "fats": "24-26g",
        "carbs": "52-55g",
        "vitamins": "Vit C, Vit A, Calcium",
        "is_available": True,
        "popularity": 94,
    },
    {
        "slug": "chocolate-strawberry-mousse",
        "name": "Chocolate Strawberry Mousse",
        "description": (
            "Dark chocolate mousse with fresh strawberries and a sprinkle of cocoa nibs."
        ),
        "category": "DESSERT",
        "price_cents": 1200,
        "weight_grams": 200,
        "calories": 470,
        "protein": "8-10g",
        "fats": "30-33g",
        "carbs": "40-43g",
        "vitamins": "Iron, Magnesium, Vit C",
        "is_available": True,
        "popularity": 112,
    },
]

dishes = sa.table(
    "dishes",
    sa.column("slug", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.String),
    sa.column("category", sa.Enum(name="dish_category", create_type=False)),
    sa.column("price_cents", sa.Integer),
    sa.column("weight_grams", sa.Integer),
    sa.column("calories", sa.Integer),
    sa.column("protein", sa.String),
    sa.column("fats", sa.String),
    sa.column("carbs", sa.String),
    sa.column("vitamins", sa.String),
    sa.column("is_available", sa.Boolean),
    sa.column("popularity", sa.Integer),
    sa.column("image_key", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    rows = [
        {
            **dish,
            "image_key": f"dishes/{dish['slug']}.jpg",
            # The first dish is the newest, so NEWEST follows the list order.
            "created_at": NEWEST - timedelta(minutes=position),
            "updated_at": NEWEST - timedelta(minutes=position),
        }
        for position, dish in enumerate(DISHES)
    ]
    # A database the seed script already filled keeps its rows.
    op.execute(insert(dishes).values(rows).on_conflict_do_nothing(index_elements=["slug"]))


def downgrade() -> None:
    op.execute(dishes.delete().where(dishes.c.slug.in_([dish["slug"] for dish in DISHES])))

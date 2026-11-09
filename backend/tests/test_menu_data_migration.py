import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.anyio


async def test_migrations_fill_the_menu_with_thirty_dishes(connection: AsyncConnection) -> None:
    rows = (
        await connection.execute(
            text("SELECT category::text, count(*) FROM dishes GROUP BY category ORDER BY 1")
        )
    ).all()

    assert rows == [("APPETIZER", 10), ("DESSERT", 10), ("MAIN_COURSE", 10)]


async def test_every_dish_points_at_its_picture_key(connection: AsyncConnection) -> None:
    mismatched = await connection.scalar(
        text("SELECT count(*) FROM dishes WHERE image_key <> 'dishes/' || slug || '.jpg'")
    )

    assert mismatched == 0


async def test_the_first_dish_of_the_file_is_the_newest(connection: AsyncConnection) -> None:
    newest = await connection.scalar(
        text("SELECT slug FROM dishes ORDER BY created_at DESC LIMIT 1")
    )

    assert newest == "pkhali-trio"

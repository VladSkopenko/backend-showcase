from itertools import pairwise

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.anyio


CAPACITIES = {
    "48-rustaveli-avenue": [2, 2, 2, 4, 4, 4, 4, 6, 6, 8],
    "14-baratashvili-street": [2, 2, 2, 2, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 8, 8],
    "9-abashidze-street": [2, 2, 2, 2, 2, 4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 6, 8, 8],
}


async def test_migrations_ship_the_three_locations_in_order(connection: AsyncConnection) -> None:
    rows = (
        await connection.execute(
            text("SELECT slug, address, image_key, created_at FROM locations ORDER BY created_at")
        )
    ).all()

    assert [(row.slug, row.address, row.image_key) for row in rows] == [
        ("48-rustaveli-avenue", "48 Rustaveli Avenue", "locations/48-rustaveli-avenue.jpg"),
        (
            "14-baratashvili-street",
            "14 Baratashvili Street",
            "locations/14-baratashvili-street.jpg",
        ),
        ("9-abashidze-street", "9 Abashidze Street", "locations/9-abashidze-street.jpg"),
    ]
    timestamps = [row.created_at for row in rows]
    assert all(earlier < later for earlier, later in pairwise(timestamps))


async def test_migrations_ship_every_table_with_its_capacity(connection: AsyncConnection) -> None:
    rows = (
        await connection.execute(
            text(
                "SELECT l.slug, t.label, t.capacity FROM dining_tables t "
                "JOIN locations l ON l.id = t.location_id "
                "ORDER BY l.created_at, split_part(t.label, ' ', 2)::int"
            )
        )
    ).all()

    assert [tuple(row) for row in rows] == [
        (slug, f"Table {number}", capacity)
        for slug, capacities in CAPACITIES.items()
        for number, capacity in enumerate(capacities, start=1)
    ]

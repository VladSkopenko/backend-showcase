import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.core.menu.enums import DishCategory
from app.model_registry import User
from support.bookings import Venue
from support.preorder import Menu, Party, add_party, make_dish


@pytest.fixture
async def menu(session_factory: async_sessionmaker[AsyncSession]) -> Menu:
    menu = Menu(
        soup=make_dish("test-soup", DishCategory.APPETIZER, 850, 10, True),
        steak=make_dish("test-steak", DishCategory.MAIN_COURSE, 2400, 25, True),
        cake=make_dish("test-cake", DishCategory.DESSERT, 650, 15, True),
        gone=make_dish("test-gone", DishCategory.MAIN_COURSE, 1800, 20, False),
    )
    async with session_factory() as session:
        session.add_all([menu.soup, menu.steak, menu.cake, menu.gone])
        await session.commit()
    return menu


@pytest.fixture
async def party(
    session_factory: async_sessionmaker[AsyncSession], venue: Venue, users: dict[str, User]
) -> Party:
    return await add_party(session_factory, venue, users)

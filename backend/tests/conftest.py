from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.common import database
from app.config.settings import get_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# Sync on purpose: the async env.py calls asyncio.run, which cannot run inside a test's event loop.
@pytest.fixture(scope="session")
def migrated_database() -> None:
    command.upgrade(Config(Path(__file__).resolve().parents[1] / "alembic.ini"), "head")


@pytest.fixture
async def engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(get_settings().database.url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside an outer transaction that is rolled back after each test."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()


@pytest.fixture
def session_factory(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> async_sessionmaker[AsyncSession]:
    """Points get_session at the test connection; its commits only release a savepoint."""
    factory = async_sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    monkeypatch.setattr(database, "get_sessionmaker", lambda: factory)
    return factory

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.common import database
from app.config import settings as settings_module
from app.config.settings import get_settings

# A developer's backend/.env must never change test behaviour or send mail. Runs at collection,
# before any test module builds the app and fills the cached get_settings().
for value in vars(settings_module).values():
    if isinstance(value, type) and issubclass(value, BaseSettings) and value is not BaseSettings:
        value.model_config["env_file"] = None


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # DATABASE_ variables stay, so a test run can point at another database.
    for name in list(os.environ):
        if name.startswith(("APP_", "EMAIL_", "AUTH_")):
            monkeypatch.delenv(name)


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

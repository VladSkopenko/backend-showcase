import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings
from sqlalchemy import text
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

TEST_DATABASE_NAME = "app_test"

# Set before any test module builds the app, which reads the settings at import and caches them.
for name in list(os.environ):
    if name.startswith("TOKEN_"):
        del os.environ[name]
os.environ["TOKEN_SECRET_KEY"] = "0123456789abcdef" * 4
os.environ["DATABASE_NAME"] = TEST_DATABASE_NAME
os.environ.pop("APP_ENVIRONMENT", None)
TEST_MEDIA_PUBLIC_BASE_URL = "https://media.example.com/n/ns/b/media/o"
for name in list(os.environ):
    if name.startswith("MEDIA_"):
        del os.environ[name]
os.environ["MEDIA_PUBLIC_BASE_URL"] = TEST_MEDIA_PUBLIC_BASE_URL

# A developer's backend/.env must never change test behaviour or send mail. Runs at collection,
# before any test module builds the app and fills the cached get_settings().
for value in vars(settings_module).values():
    if isinstance(value, type) and issubclass(value, BaseSettings) and value is not BaseSettings:
        value.model_config["env_file"] = None


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # DATABASE_ variables stay, so a test run can point at another server; the name is forced above.
    for name in list(os.environ):
        if name.startswith(("APP_", "EMAIL_", "AUTH_", "GOOGLE_", "MEDIA_", "BOOKING_")):
            monkeypatch.delenv(name)
    # Required by the settings; the write keys stay unset, so nothing can reach a bucket.
    monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", TEST_MEDIA_PUBLIC_BASE_URL)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def recreate_test_database() -> None:
    # Dropped and recreated per run, so two runs on one server break each other.
    # DROP DATABASE and CREATE DATABASE refuse to run inside a transaction block.
    engine = create_async_engine(
        get_settings().database.url.set(database="postgres"),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}" WITH (FORCE)')
            )
            await connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}"'))
    finally:
        await engine.dispose()


# Sync on purpose: the async env.py calls asyncio.run, which cannot run inside a test's event loop.
@pytest.fixture(scope="session")
def migrated_database() -> None:
    database_name = get_settings().database.name
    if database_name != TEST_DATABASE_NAME:
        pytest.exit(
            f"Settings were cached with database {database_name!r} before conftest forced "
            f"{TEST_DATABASE_NAME!r}; refusing to recreate or migrate it."
        )
    asyncio.run(recreate_test_database())
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

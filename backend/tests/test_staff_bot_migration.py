import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, delete, func, select
from sqlalchemy.ext.asyncio import AsyncConnection
from support.bookings import WAITER_BOT

from app.model_registry import User

pytestmark = pytest.mark.anyio

BOT_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Lf2JoTtceyf2Fd6S/nVkYg$"
    "DtRYerfEvFEpwj+u7XZvNnKmV8N8DGK0iDm+br4R0OM"
)
REVISION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0018_add_staff_bot.py"
)


def load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("revision_0018", REVISION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_revision(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, *, step: str, environment: str
) -> None:
    revision = load_revision()
    settings = SimpleNamespace(app=SimpleNamespace(environment=environment))
    monkeypatch.setattr(revision, "get_settings", lambda: settings)

    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            getattr(revision, step)()

    await connection.run_sync(run)


async def count_bots(connection: AsyncConnection) -> int:
    count = await connection.scalar(
        select(func.count()).select_from(User).where(User.email == WAITER_BOT)
    )
    assert count is not None
    return count


async def test_migrations_add_the_staff_bot_locally(connection: AsyncConnection) -> None:
    rows = (
        await connection.execute(
            select(
                User.first_name,
                User.last_name,
                User.is_staff,
                User.email_verified_at.is_not(None),
                User.password_hash,
            ).where(User.email == WAITER_BOT)
        )
    ).all()

    assert [tuple(row) for row in rows] == [("Waiter", "Bot", True, True, BOT_PASSWORD_HASH)]


# The outer test transaction is rolled back afterwards, so later tests still see the bot.
@pytest.mark.parametrize("environment", ["staging", "prod"])
async def test_the_staff_bot_is_never_added_on_staging_or_prod(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    await connection.execute(delete(User).where(User.email == WAITER_BOT))

    await run_revision(connection, monkeypatch, step="upgrade", environment=environment)

    assert await count_bots(connection) == 0


async def test_the_downgrade_removes_the_staff_bot_locally(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_revision(connection, monkeypatch, step="downgrade", environment="local")

    assert await count_bots(connection) == 0

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

BOT_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Lf2JoTtceyf2Fd6S/nVkYg$"
    "DtRYerfEvFEpwj+u7XZvNnKmV8N8DGK0iDm+br4R0OM"
)
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def load_revision(file_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(Path(file_name).stem, VERSIONS / file_name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_revision(
    connection: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
    *,
    file_name: str,
    step: str,
    environment: str,
) -> None:
    revision = load_revision(file_name)
    settings = SimpleNamespace(app=SimpleNamespace(environment=environment))
    monkeypatch.setattr(revision, "get_settings", lambda: settings)

    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            getattr(revision, step)()

    await connection.run_sync(run)

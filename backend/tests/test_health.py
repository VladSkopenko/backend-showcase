import logging
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config.settings import DatabaseSettings, Settings, get_settings
from app.features.core.health.endpoints.dependencies import get_database_engine
from app.features.core.health.repositories import DatabaseProbeRepository
from app.main import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.fixture
async def unreachable_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(get_settings().database.url.set(port=1), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def wrong_password_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        get_settings().database.url.set(password="wrong"), poolclass=NullPool
    )
    yield engine
    await engine.dispose()


async def test_health_reports_ok_when_the_database_answers(
    app: FastAPI, client: httpx2.AsyncClient, engine: AsyncEngine
) -> None:
    app.dependency_overrides[get_database_engine] = lambda: engine

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_reports_unavailable_when_the_database_refuses_connections(
    app: FastAPI, client: httpx2.AsyncClient, unreachable_engine: AsyncEngine
) -> None:
    app.dependency_overrides[get_database_engine] = lambda: unreachable_engine

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


async def test_health_reports_unavailable_when_the_credentials_are_wrong(
    app: FastAPI, client: httpx2.AsyncClient, wrong_password_engine: AsyncEngine
) -> None:
    app.dependency_overrides[get_database_engine] = lambda: wrong_password_engine

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


async def test_health_reports_unavailable_when_the_ping_exceeds_the_timeout(
    app: FastAPI,
    client: httpx2.AsyncClient,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def slow_ping(self: DatabaseProbeRepository) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT pg_sleep(2)"))

    monkeypatch.setattr(DatabaseProbeRepository, "ping", slow_ping)
    settings = Settings(database=DatabaseSettings(probe_timeout_seconds=0.2))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_database_engine] = lambda: engine

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == []


async def test_root_says_service_works(client: httpx2.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "backend-showcase works"}


async def test_openapi_lists_health_schema(client: httpx2.AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "backend-showcase"
    responses = spec["paths"]["/health"]["get"]["responses"]
    for code in ("200", "503"):
        schema_ref = responses[code]["content"]["application/json"]["schema"]["$ref"]
        assert schema_ref == "#/components/schemas/HealthResponse"
    properties = spec["components"]["schemas"]["HealthResponse"]["properties"]
    assert properties["status"]["enum"] == ["ok", "error"]
    assert properties["database"]["enum"] == ["ok", "unavailable"]

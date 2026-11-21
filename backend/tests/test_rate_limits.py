from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import RateLimitSettings
from app.features.core.auth.endpoints.dependencies import get_email_sender
from app.infrastructure.rate_limit import limiter
from app.main import create_app

PASSWORD = "correct horse battery staple"
REGISTRATIONS_PER_MINUTE = 15
REQUESTS_PER_MINUTE = 300

pytestmark = pytest.mark.anyio


class SilentEmailSender:
    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        return None


@pytest.fixture
def rate_limits_on(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)


@pytest.fixture
def app(rate_limits_on: None) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_email_sender] = SilentEmailSender
    return app


def client_from(app: FastAPI, address: str) -> httpx2.AsyncClient:
    transport = httpx2.ASGITransport(app=app, client=(address, 50000))
    return httpx2.AsyncClient(transport=transport, base_url="https://test")


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx2.AsyncClient]:
    async with client_from(app, "203.0.113.10") as client:
        yield client


async def register(client: httpx2.AsyncClient, number: int) -> httpx2.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": f"ada-{number}@example.com",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )


async def test_registration_is_refused_after_fifteen_requests_in_a_minute(
    client: httpx2.AsyncClient,
) -> None:
    for number in range(REGISTRATIONS_PER_MINUTE):
        response = await register(client, number)
        assert response.status_code == 201, response.text

    refused = await register(client, REGISTRATIONS_PER_MINUTE)

    assert refused.status_code == 429
    body = refused.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["message"] == "Too many requests. Try again later."
    assert 1 <= body["retry_after"] <= 60
    assert refused.headers["Retry-After"] == str(body["retry_after"])
    assert set(body) == {"code", "message", "retry_after"}


async def test_another_address_is_counted_separately(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    for number in range(REGISTRATIONS_PER_MINUTE + 1):
        await register(client, number)

    async with client_from(app, "203.0.113.20") as other:
        response = await register(other, 100)

    assert response.status_code == 201, response.text


async def test_any_route_is_refused_after_three_hundred_requests_in_a_minute(
    client: httpx2.AsyncClient,
) -> None:
    for _ in range(REQUESTS_PER_MINUTE):
        response = await client.get("/api/v1/locations")
        assert response.status_code == 200, response.text

    refused = await client.get("/api/v1/locations")

    assert refused.status_code == 429
    assert refused.json()["code"] == "RATE_LIMITED"
    assert 1 <= refused.json()["retry_after"] <= 60


async def test_requests_are_served_when_the_limit_storage_is_down(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_hit(*args: object, **kwargs: object) -> bool:
        raise ConnectionError("storage is down")

    monkeypatch.setattr(limiter.limiter, "hit", broken_hit)

    health = await client.get("/api/v1/locations")
    registered = await register(client, 0)

    assert health.status_code == 200, health.text
    assert registered.status_code == 201, registered.text


def test_limits_are_kept_in_memory_by_default() -> None:
    assert RateLimitSettings().storage_uri == "memory://"


def test_the_limit_storage_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "redis://redis:6379")

    assert RateLimitSettings().storage_uri == "redis://redis:6379"

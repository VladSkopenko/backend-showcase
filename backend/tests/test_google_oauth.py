from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.common import clock
from app.config.settings import GoogleSettings, Settings, get_settings
from app.features.core.auth.endpoints.dependencies import get_oauth_clients
from app.features.core.auth.enums import OAuthProvider
from app.infrastructure.oauth import OAuthExchangeError
from app.main import create_app
from app.model_registry import OAuthAccount, RefreshToken, User

pytestmark = pytest.mark.anyio

START = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
AUTH = "/api/v1/auth"
FRONTEND = "https://family-rest.vercel.app"
EMAIL = "ada@example.com"
SUBJECT = "google-sub-1"
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth?state=fake-state"
CLAIMS: dict[str, Any] = {
    "sub": SUBJECT,
    "email": EMAIL,
    "email_verified": True,
    "given_name": "Ada",
    "family_name": "Lovelace",
}


@dataclass
class FakeOAuthClients:
    """Stands in for OAuthClients: no network, but it writes request.session like authlib."""

    claims: dict[str, Any] = field(default_factory=lambda: dict(CLAIMS))
    failure: OAuthExchangeError | None = None
    redirect_uris: list[str] = field(default_factory=list)

    async def authorize_redirect(
        self, *, request: Request, provider_slug: str, redirect_uri: str
    ) -> Response:
        if self.failure is not None:
            request.session.clear()
            raise self.failure
        self.redirect_uris.append(redirect_uri)
        request.session["_state_google_fake-state"] = {"redirect_uri": redirect_uri}
        return RedirectResponse(GOOGLE_AUTHORIZE_URL, status_code=302)

    async def fetch_claims(self, *, request: Request, provider_slug: str) -> dict[str, Any]:
        request.session.clear()
        if self.failure is not None:
            raise self.failure
        return self.claims


@dataclass
class FakeClock:
    current: datetime = START

    def now(self) -> datetime:
        return self.current


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clock, "now", fake.now)
    return fake


@pytest.fixture
def google_configured() -> bool:
    return True


@pytest.fixture
def oauth_clients() -> FakeOAuthClients:
    return FakeOAuthClients()


@pytest.fixture
def app(oauth_clients: FakeOAuthClients, google_configured: bool) -> FastAPI:
    app = create_app()
    google = (
        GoogleSettings(client_id="client-id", client_secret=SecretStr("client-secret"))
        if google_configured
        else GoogleSettings(client_id="", client_secret=SecretStr(""))
    )
    settings = Settings(google=google)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_oauth_clients] = lambda: oauth_clients
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


def set_cookies(response: httpx2.Response) -> dict[str, dict[str, str]]:
    """Parses raw Set-Cookie headers: name -> {"value": ..., lowercased attribute -> value}."""
    cookies: dict[str, dict[str, str]] = {}
    for header in response.headers.get_list("set-cookie"):
        pair, *attributes = (part.strip() for part in header.split(";"))
        name, value = pair.split("=", 1)
        parsed = {"value": value}
        for attribute in attributes:
            key, _, attribute_value = attribute.partition("=")
            parsed[key.lower()] = attribute_value
        cookies[name] = parsed
    return cookies


async def start(client: httpx2.AsyncClient, slug: str = "google") -> httpx2.Response:
    return await client.get(f"{AUTH}/{slug}/login")


async def callback(
    client: httpx2.AsyncClient, slug: str = "google", **params: str
) -> httpx2.Response:
    return await client.get(f"{AUTH}/{slug}/callback", params=params)


async def sign_in(client: httpx2.AsyncClient) -> httpx2.Response:
    assert (await start(client)).status_code == 302
    return await callback(client, code="auth-code", state="fake-state")


def assert_error_redirect(response: httpx2.Response, code: str) -> None:
    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONTEND}/?auth_error={code}"
    assert {"access_token", "refresh_token"}.isdisjoint(set_cookies(response))


def assert_state_cookie_deleted(response: httpx2.Response) -> None:
    state = set_cookies(response)["oauth_state"]
    assert state["value"] == "null"
    assert state["path"] == "/api/v1/auth"
    assert state["expires"] == "Thu, 01 Jan 1970 00:00:00 GMT"


def assert_signed_in(response: httpx2.Response) -> None:
    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONTEND}/"
    cookies = set_cookies(response)
    assert {"access_token", "refresh_token"} <= set(cookies)
    assert_state_cookie_deleted(response)


async def add_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = EMAIL,
    verified: bool = True,
    password_hash: str | None = "stored-hash",
    **fields: Any,
) -> User:
    async with session_factory() as session:
        user = User(
            first_name="Pre",
            last_name="Registered",
            email=email,
            password_hash=password_hash,
            email_verified_at=START - timedelta(days=1) if verified else None,
            **fields,
        )
        session.add(user)
        await session.commit()
    return user


async def link(
    session_factory: async_sessionmaker[AsyncSession], user: User, subject: str = SUBJECT
) -> None:
    async with session_factory() as session:
        session.add(
            OAuthAccount(
                user_id=user.id,
                provider=OAuthProvider.GOOGLE,
                subject=subject,
                created_at=START - timedelta(days=1),
            )
        )
        await session.commit()


async def get_user(connection: AsyncConnection, email: str = EMAIL) -> Any:
    return (await connection.execute(select(User).where(User.email == email))).one_or_none()


async def get_links(connection: AsyncConnection) -> list[Any]:
    result = await connection.execute(select(OAuthAccount).order_by(OAuthAccount.created_at))
    return list(result.all())


async def count(connection: AsyncConnection, model: type[Any]) -> int:
    value = await connection.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


async def test_login_redirects_to_google_with_the_frontend_callback_and_a_state_cookie(
    client: httpx2.AsyncClient, oauth_clients: FakeOAuthClients
) -> None:
    response = await start(client)

    assert response.status_code == 302
    assert response.headers["location"] == GOOGLE_AUTHORIZE_URL
    assert oauth_clients.redirect_uris == [f"{FRONTEND}/api/v1/auth/google/callback"]
    state = set_cookies(response)["oauth_state"]
    assert state["path"] == "/api/v1/auth"
    assert state["max-age"] == "600"
    assert state["samesite"] == "lax"
    assert "httponly" in state
    assert "secure" in state


@pytest.mark.parametrize("google_configured", [False])
@pytest.mark.parametrize("route", ["login", "callback"])
async def test_unconfigured_provider_redirects_with_oauth_unavailable(
    client: httpx2.AsyncClient, route: str
) -> None:
    response = await client.get(f"{AUTH}/google/{route}")

    assert_error_redirect(response, "OAUTH_UNAVAILABLE")
    assert "oauth_state" not in set_cookies(response)


async def test_login_with_unreachable_metadata_redirects_with_oauth_failed(
    client: httpx2.AsyncClient, oauth_clients: FakeOAuthClients
) -> None:
    oauth_clients.failure = OAuthExchangeError()

    response = await start(client)

    assert_error_redirect(response, "OAUTH_FAILED")
    assert "oauth_state" not in set_cookies(response)


@pytest.mark.parametrize("route", ["login", "callback"])
async def test_unknown_provider_is_404(client: httpx2.AsyncClient, route: str) -> None:
    response = await client.get(f"{AUTH}/github/{route}")

    assert response.status_code == 404


async def test_linked_user_signs_in_by_subject_ignoring_the_lockout(
    client: httpx2.AsyncClient,
    oauth_clients: FakeOAuthClients,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    locked_until = START + timedelta(minutes=5)
    user = await add_user(session_factory, failed_login_attempts=3, login_locked_until=locked_until)
    await link(session_factory, user)
    oauth_clients.claims = {**CLAIMS, "email": "changed@example.com", "email_verified": False}

    response = await sign_in(client)

    assert_signed_in(response)
    stored = await get_user(connection)
    assert stored.failed_login_attempts == 3
    assert stored.login_locked_until == locked_until
    assert await count(connection, RefreshToken) == 1
    assert await count(connection, User) == 1
    assert (await client.get(f"{AUTH}/me")).json()["email"] == EMAIL


async def test_verified_email_links_a_verified_account_and_keeps_its_password(
    client: httpx2.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    user = await add_user(session_factory)

    response = await sign_in(client)

    assert_signed_in(response)
    [stored_link] = await get_links(connection)
    assert (stored_link.user_id, stored_link.provider, stored_link.subject) == (
        user.id,
        OAuthProvider.GOOGLE,
        SUBJECT,
    )
    assert stored_link.created_at == START
    stored = await get_user(connection)
    assert stored.password_hash == "stored-hash"
    assert stored.email_verified_at == START - timedelta(days=1)


async def test_verified_email_links_an_unverified_account_verifies_it_and_wipes_the_password(
    client: httpx2.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    user = await add_user(session_factory, verified=False)

    response = await sign_in(client)

    assert_signed_in(response)
    [stored_link] = await get_links(connection)
    assert stored_link.user_id == user.id
    stored = await get_user(connection)
    assert stored.email_verified_at == START
    assert stored.password_hash is None


async def test_verified_email_without_an_account_creates_a_verified_user(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    response = await sign_in(client)

    assert_signed_in(response)
    stored = await get_user(connection)
    assert (stored.first_name, stored.last_name) == ("Ada", "Lovelace")
    assert stored.email_verified_at == START
    assert stored.password_hash is None
    [stored_link] = await get_links(connection)
    assert (stored_link.user_id, stored_link.subject) == (stored.id, SUBJECT)
    assert (await client.get(f"{AUTH}/me")).json()["email"] == EMAIL


async def test_new_user_names_follow_the_fallbacks(
    client: httpx2.AsyncClient, oauth_clients: FakeOAuthClients, connection: AsyncConnection
) -> None:
    oauth_clients.claims = {"sub": SUBJECT, "email": "Ada.L@Example.com", "email_verified": True}

    assert_signed_in(await sign_in(client))

    stored = await get_user(connection, "ada.l@example.com")
    assert (stored.first_name, stored.last_name) == ("Ada.L", "")


async def test_email_of_a_user_linked_to_another_google_account_is_a_conflict(
    client: httpx2.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    user = await add_user(session_factory, verified=False)
    await link(session_factory, user, subject="google-sub-original")

    response = await sign_in(client)

    assert_error_redirect(response, "OAUTH_ACCOUNT_CONFLICT")
    assert_state_cookie_deleted(response)
    assert [stored_link.subject for stored_link in await get_links(connection)] == [
        "google-sub-original"
    ]
    stored = await get_user(connection)
    assert stored.email_verified_at is None
    assert stored.password_hash == "stored-hash"
    assert await count(connection, RefreshToken) == 0


@pytest.mark.parametrize(
    "claims",
    [
        {**CLAIMS, "email_verified": False},
        {**CLAIMS, "email_verified": "false"},
        {key: value for key, value in CLAIMS.items() if key != "email_verified"},
        {key: value for key, value in CLAIMS.items() if key != "email"},
    ],
)
async def test_unverified_google_email_without_a_link_is_refused(
    client: httpx2.AsyncClient,
    oauth_clients: FakeOAuthClients,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    claims: dict[str, Any],
) -> None:
    await add_user(session_factory, verified=False)
    oauth_clients.claims = claims

    response = await sign_in(client)

    assert_error_redirect(response, "OAUTH_EMAIL_UNVERIFIED")
    assert_state_cookie_deleted(response)
    assert await get_links(connection) == []
    assert await count(connection, User) == 1
    assert (await get_user(connection)).password_hash == "stored-hash"


async def test_cancelled_consent_redirects_with_oauth_cancelled(
    client: httpx2.AsyncClient, oauth_clients: FakeOAuthClients
) -> None:
    assert (await start(client)).status_code == 302
    oauth_clients.failure = OAuthExchangeError(cancelled=True)

    response = await callback(client, error="access_denied", state="fake-state")

    assert_error_redirect(response, "OAUTH_CANCELLED")
    assert_state_cookie_deleted(response)


async def test_failed_exchange_redirects_with_oauth_failed(
    client: httpx2.AsyncClient, oauth_clients: FakeOAuthClients, connection: AsyncConnection
) -> None:
    assert (await start(client)).status_code == 302
    oauth_clients.failure = OAuthExchangeError()

    response = await callback(client, code="auth-code", state="tampered")

    assert_error_redirect(response, "OAUTH_FAILED")
    assert_state_cookie_deleted(response)
    assert await count(connection, User) == 0
    assert await get_links(connection) == []


async def test_claims_without_sub_redirect_with_oauth_failed(
    client: httpx2.AsyncClient, oauth_clients: FakeOAuthClients, connection: AsyncConnection
) -> None:
    oauth_clients.claims = {key: value for key, value in CLAIMS.items() if key != "sub"}

    response = await sign_in(client)

    assert_error_redirect(response, "OAUTH_FAILED")
    assert await count(connection, User) == 0


async def test_user_created_by_google_cannot_log_in_with_a_password(
    client: httpx2.AsyncClient,
) -> None:
    assert_signed_in(await sign_in(client))
    client.cookies.clear()

    response = await client.post(
        f"{AUTH}/login", json={"email": EMAIL, "password": "any-password-at-all"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"

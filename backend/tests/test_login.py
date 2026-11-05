import hashlib
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common import clock
from app.config.settings import Settings, get_settings
from app.features.core.auth.endpoints.dependencies import get_email_sender
from app.main import create_app
from app.model_registry import RefreshToken, User

pytestmark = pytest.mark.anyio

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
EMAIL = "ada@example.com"
PASSWORD = "correct-horse"
WRONG_PASSWORD = "wrong-horse"
SECRET = "0123456789abcdef" * 4
AUTH = "/api/v1/auth"
PROFILE_KEYS = {"id", "email", "first_name", "last_name", "email_verified_at"}


@dataclass
class FakeEmailSender:
    sent: list[str] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        self.sent.append(to)


@dataclass
class FakeClock:
    current: datetime = START

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clock, "now", fake.now)
    return fake


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    mailbox = FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: mailbox
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


async def register(client: httpx2.AsyncClient) -> str:
    response = await client.post(
        f"{AUTH}/register",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": EMAIL,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    code: str = response.json()["debug_code"]
    return code


async def create_verified_user(client: httpx2.AsyncClient) -> None:
    """Registers and verifies Ada; verification starts a session, which stays active in the DB."""
    code = await register(client)
    response = await client.post(f"{AUTH}/verify-email", json={"email": EMAIL, "code": code})
    assert response.status_code == 200, response.text
    client.cookies.clear()


async def log_in(
    client: httpx2.AsyncClient, password: str = PASSWORD, email: str = EMAIL
) -> httpx2.Response:
    return await client.post(f"{AUTH}/login", json={"email": email, "password": password})


async def fail_logins(client: httpx2.AsyncClient, times: int) -> None:
    for _ in range(times):
        assert (await log_in(client, WRONG_PASSWORD)).status_code == 401


async def refresh(client: httpx2.AsyncClient, **headers: str) -> httpx2.Response:
    return await client.post(f"{AUTH}/refresh", headers=headers)


async def log_out(client: httpx2.AsyncClient, **headers: str) -> httpx2.Response:
    return await client.post(f"{AUTH}/logout", headers=headers)


async def me(client: httpx2.AsyncClient, **headers: str) -> httpx2.Response:
    return await client.get(f"{AUTH}/me", headers=headers)


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


def assert_session_cookies_set(response: httpx2.Response) -> dict[str, dict[str, str]]:
    cookies = set_cookies(response)
    assert set(cookies) == {"access_token", "refresh_token"}
    access, refresh_cookie = cookies["access_token"], cookies["refresh_token"]
    assert access["path"] == "/"
    assert access["max-age"] == str(15 * 60)
    assert refresh_cookie["path"] == "/api/v1/auth"
    assert refresh_cookie["max-age"] == str(30 * 24 * 60 * 60)
    for cookie in (access, refresh_cookie):
        assert cookie["value"] not in ("", '""')
        assert "httponly" in cookie
        assert "secure" in cookie
        assert cookie["samesite"].lower() == "lax"
        assert "domain" not in cookie
    return cookies


def assert_session_cookies_cleared(response: httpx2.Response) -> None:
    cookies = set_cookies(response)
    assert set(cookies) == {"access_token", "refresh_token"}
    assert cookies["access_token"]["path"] == "/"
    assert cookies["refresh_token"]["path"] == "/api/v1/auth"
    for cookie in cookies.values():
        assert cookie["value"] in ("", '""')
        assert cookie["max-age"] == "0"
        assert "httponly" in cookie
        assert "secure" in cookie
        assert cookie["samesite"].lower() == "lax"
        assert "domain" not in cookie


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_user(connection: AsyncConnection) -> Any:
    return (await connection.execute(select(User).where(User.email == EMAIL))).one()


async def get_refresh_tokens(connection: AsyncConnection) -> list[Any]:
    user = await get_user(connection)
    result = await connection.execute(
        select(RefreshToken)
        .where(RefreshToken.user_id == user.id)
        .order_by(RefreshToken.created_at, RefreshToken.id)
    )
    return list(result.all())


async def get_refresh_token(connection: AsyncConnection, token: str) -> Any:
    result = await connection.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash(token))
    )
    return result.one()


def access_token(
    *, key: str = SECRET, algorithm: str = "HS256", omit: str | None = None, **claims: Any
) -> str:
    now = int(START.timestamp())
    payload = {"sub": str(uuid.uuid4()), "iat": now, "exp": now + 15 * 60} | claims
    if omit is not None:
        del payload[omit]
    return jwt.encode(payload, key, algorithm=algorithm)


async def test_login_sets_both_cookies_and_returns_the_profile(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    await fail_logins(client, 2)

    response = await log_in(client)

    assert response.status_code == 200
    body = response.json()
    user = await get_user(connection)
    assert body == {
        "id": str(user.id),
        "email": EMAIL,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email_verified_at": START.isoformat().replace("+00:00", "Z"),
    }
    cookies = assert_session_cookies_set(response)
    assert cookies["access_token"]["value"] not in response.text
    assert cookies["refresh_token"]["value"] not in response.text
    assert user.failed_login_attempts == 0
    stored = await get_refresh_token(connection, cookies["refresh_token"]["value"])
    assert stored.expires_at == START + timedelta(days=30)
    assert stored.revoked_at is None
    claims = jwt.decode(
        cookies["access_token"]["value"],
        SECRET,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims == {
        "sub": str(user.id),
        "iat": int(START.timestamp()),
        "exp": int(START.timestamp()) + 15 * 60,
    }


async def test_wrong_password_returns_401_and_counts_the_attempt(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)

    response = await log_in(client, WRONG_PASSWORD)

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIALS",
        "message": response.json()["message"],
    }
    assert "set-cookie" not in response.headers
    assert (await get_user(connection)).failed_login_attempts == 1


async def test_fifth_wrong_password_locks_login_for_five_minutes(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    await fail_logins(client, 4)

    response = await log_in(client, WRONG_PASSWORD)

    assert response.status_code == 423
    assert response.json() == {
        "code": "ACCOUNT_LOCKED",
        "message": "Too many failed attempts. Try again in 5 minutes.",
    }
    assert "retry-after" not in response.headers
    user = await get_user(connection)
    assert user.login_locked_until == START + timedelta(minutes=5)
    assert user.failed_login_attempts == 0


@pytest.mark.parametrize("password", [PASSWORD, WRONG_PASSWORD], ids=["correct", "wrong"])
async def test_locked_login_returns_423_for_any_password(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock, password: str
) -> None:
    await create_verified_user(client)
    await fail_logins(client, 4)
    assert (await log_in(client, WRONG_PASSWORD)).status_code == 423
    fake_clock.advance(minutes=4, seconds=59)

    response = await log_in(client, password)

    assert response.status_code == 423
    assert response.json()["code"] == "ACCOUNT_LOCKED"
    assert "set-cookie" not in response.headers
    user = await get_user(connection)
    assert user.failed_login_attempts == 0
    assert user.login_locked_until == START + timedelta(minutes=5)


async def test_correct_password_after_the_lock_expires_logs_in(
    client: httpx2.AsyncClient, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    await fail_logins(client, 4)
    assert (await log_in(client, WRONG_PASSWORD)).status_code == 423
    fake_clock.advance(minutes=5)

    response = await log_in(client)

    assert response.status_code == 200
    assert_session_cookies_set(response)


async def test_wrong_password_after_the_lock_expires_counts_from_one(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    await fail_logins(client, 4)
    assert (await log_in(client, WRONG_PASSWORD)).status_code == 423
    fake_clock.advance(minutes=5)

    response = await log_in(client, WRONG_PASSWORD)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert (await get_user(connection)).failed_login_attempts == 1


async def test_locked_user_can_still_refresh(client: httpx2.AsyncClient) -> None:
    await create_verified_user(client)
    assert (await log_in(client)).status_code == 200
    await fail_logins(client, 4)
    assert (await log_in(client, WRONG_PASSWORD)).status_code == 423

    response = await refresh(client)

    assert response.status_code == 204
    assert_session_cookies_set(response)
    assert (await me(client)).status_code == 200


async def test_unknown_email_returns_401(client: httpx2.AsyncClient) -> None:
    response = await log_in(client, email="nobody@example.com")

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert "set-cookie" not in response.headers


async def test_user_without_a_password_returns_401(
    client: httpx2.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            User(first_name="Ada", last_name="Lovelace", email=EMAIL, email_verified_at=START)
        )

    response = await log_in(client)

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_correct_password_on_an_unverified_email_returns_403_and_resets_the_counter(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await register(client)
    await fail_logins(client, 1)
    assert (await get_user(connection)).failed_login_attempts == 1

    response = await log_in(client)

    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"
    assert "set-cookie" not in response.headers
    assert (await get_user(connection)).failed_login_attempts == 0
    assert await get_refresh_tokens(connection) == []


async def test_verify_email_sets_both_session_cookies(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    code = await register(client)

    response = await client.post(f"{AUTH}/verify-email", json={"email": EMAIL, "code": code})

    assert response.status_code == 200
    assert set(response.json()) == {"id", "email", "email_verified_at"}
    assert_session_cookies_set(response)
    assert len(await get_refresh_tokens(connection)) == 1
    assert (await me(client)).status_code == 200


async def test_me_returns_the_profile(client: httpx2.AsyncClient) -> None:
    await create_verified_user(client)
    profile = (await log_in(client)).json()

    response = await me(client)

    assert response.status_code == 200
    assert response.json() == profile
    assert set(profile) == PROFILE_KEYS


@pytest.mark.parametrize(
    "build_token",
    [
        lambda sub: None,
        lambda sub: "not-a-jwt",
        lambda sub: access_token(sub=sub, key="f" * 64),
        lambda sub: access_token(sub="not-a-uuid"),
        lambda sub: access_token(),
        lambda sub: access_token(sub=sub, omit="exp"),
        lambda sub: access_token(sub=sub, omit="iat"),
        lambda sub: access_token(omit="sub"),
        lambda sub: access_token(sub=sub, exp=int(START.timestamp()) + 15 * 60 + 0.5),
        lambda sub: access_token(sub=sub, exp=str(int(START.timestamp()) + 15 * 60)),
        lambda sub: access_token(sub=sub, algorithm="HS512"),
        lambda sub: access_token(sub=sub, key="", algorithm="none"),
    ],
    ids=[
        "missing",
        "malformed",
        "bad-signature",
        "non-uuid-sub",
        "unknown-user",
        "no-exp",
        "no-iat",
        "no-sub",
        "float-exp",
        "string-exp",
        "hs512",
        "alg-none",
    ],
)
async def test_me_without_a_valid_session_returns_401(
    client: httpx2.AsyncClient,
    connection: AsyncConnection,
    build_token: Callable[[str], str | None],
) -> None:
    # Built for a real user, so each token fails for its own defect, not at the user lookup.
    await create_verified_user(client)
    sub = str((await get_user(connection)).id)
    assert (await me(client, Cookie=f"access_token={access_token(sub=sub)}")).status_code == 200
    token = build_token(sub)
    headers = {} if token is None else {"Cookie": f"access_token={token}"}

    response = await me(client, **headers)

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"
    assert "set-cookie" not in response.headers


async def test_login_with_a_differently_cased_email_succeeds(client: httpx2.AsyncClient) -> None:
    await create_verified_user(client)

    response = await log_in(client, email="ADA@Example.com")

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL
    assert_session_cookies_set(response)


async def test_me_with_an_expired_access_token_returns_401(
    client: httpx2.AsyncClient, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    assert (await log_in(client)).status_code == 200
    fake_clock.advance(minutes=14, seconds=59)
    assert (await me(client)).status_code == 200
    fake_clock.advance(minutes=1, seconds=1)

    response = await me(client)

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"


async def test_access_token_copied_before_logout_still_works(client: httpx2.AsyncClient) -> None:
    await create_verified_user(client)
    copied = set_cookies(await log_in(client))["access_token"]["value"]
    assert (await log_out(client)).status_code == 204
    assert (await me(client)).status_code == 401

    response = await me(client, Cookie=f"access_token={copied}")

    assert response.status_code == 200


async def test_refresh_rotates_both_cookies_and_revokes_the_old_token(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    first = set_cookies(await log_in(client))
    fake_clock.advance(minutes=1)

    response = await refresh(client)

    assert response.status_code == 204
    assert response.content == b""
    second = assert_session_cookies_set(response)
    assert second["access_token"]["value"] != first["access_token"]["value"]
    assert second["refresh_token"]["value"] != first["refresh_token"]["value"]
    old = await get_refresh_token(connection, first["refresh_token"]["value"])
    assert old.revoked_at == fake_clock.current
    assert old.rotated_at == fake_clock.current
    new = await get_refresh_token(connection, second["refresh_token"]["value"])
    assert new.revoked_at is None
    assert new.expires_at == fake_clock.current + timedelta(days=30)
    assert (await me(client)).status_code == 200


async def test_refresh_with_an_unknown_token_returns_401_and_clears_cookies(
    client: httpx2.AsyncClient,
) -> None:
    response = await refresh(client, Cookie="refresh_token=unknown")

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_INVALID"
    assert_session_cookies_cleared(response)


async def test_refresh_with_an_expired_token_returns_401_and_clears_cookies(
    client: httpx2.AsyncClient, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    assert (await log_in(client)).status_code == 200
    fake_clock.advance(days=30)

    response = await refresh(client)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_INVALID"
    assert_session_cookies_cleared(response)


async def test_refresh_without_cookies_returns_401_without_set_cookie(
    client: httpx2.AsyncClient,
) -> None:
    response = await refresh(client)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_INVALID"
    assert "set-cookie" not in response.headers


async def test_reusing_a_rotated_refresh_token_revokes_every_session(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    stolen = set_cookies(await log_in(client))["refresh_token"]["value"]
    assert (await refresh(client)).status_code == 204
    other_device = set_cookies(await log_in(client))["refresh_token"]["value"]
    fake_clock.advance(minutes=1)
    client.cookies.clear()

    response = await refresh(client, Cookie=f"refresh_token={stolen}")

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_INVALID"
    assert_session_cookies_cleared(response)
    tokens = await get_refresh_tokens(connection)
    assert len(tokens) == 4
    assert all(token.revoked_at is not None for token in tokens)
    newer = set_cookies(await log_in(client))["refresh_token"]["value"]
    client.cookies.clear()
    mass_revoked = await refresh(client, Cookie=f"refresh_token={other_device}")
    assert mass_revoked.status_code == 401
    assert_session_cookies_cleared(mass_revoked)
    assert (await get_refresh_token(connection, newer)).revoked_at is None


async def test_logout_revokes_the_token_and_clears_cookies(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    token = set_cookies(await log_in(client))["refresh_token"]["value"]

    response = await log_out(client)

    assert response.status_code == 204
    assert response.content == b""
    assert_session_cookies_cleared(response)
    stored = await get_refresh_token(connection, token)
    assert stored.revoked_at == START
    assert stored.rotated_at is None
    assert (await refresh(client, Cookie=f"refresh_token={token}")).status_code == 401


async def test_logout_with_a_rotated_token_revokes_every_session(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    stolen = set_cookies(await log_in(client))["refresh_token"]["value"]
    assert (await refresh(client)).status_code == 204
    client.cookies.clear()

    response = await log_out(client, Cookie=f"refresh_token={stolen}")

    assert response.status_code == 204
    assert_session_cookies_cleared(response)
    tokens = await get_refresh_tokens(connection)
    assert len(tokens) == 3
    assert all(token.revoked_at is not None for token in tokens)


async def log_in_out_and_in_again(client: httpx2.AsyncClient) -> tuple[str, str]:
    """Returns a logged-out refresh token and the newer session's token, with an empty jar."""
    await create_verified_user(client)
    logged_out = set_cookies(await log_in(client))["refresh_token"]["value"]
    assert (await log_out(client)).status_code == 204
    newer = set_cookies(await log_in(client))["refresh_token"]["value"]
    client.cookies.clear()
    return logged_out, newer


async def test_refresh_with_a_logged_out_token_revokes_nothing_else(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    logged_out, newer = await log_in_out_and_in_again(client)

    response = await refresh(client, Cookie=f"refresh_token={logged_out}")

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_INVALID"
    assert_session_cookies_cleared(response)
    assert (await get_refresh_token(connection, newer)).revoked_at is None
    assert len([t for t in await get_refresh_tokens(connection) if t.revoked_at is None]) == 2


async def test_logout_with_a_logged_out_token_revokes_nothing_else(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    logged_out, newer = await log_in_out_and_in_again(client)

    response = await log_out(client, Cookie=f"refresh_token={logged_out}")

    assert response.status_code == 204
    assert_session_cookies_cleared(response)
    assert (await get_refresh_token(connection, newer)).revoked_at is None
    assert len([t for t in await get_refresh_tokens(connection) if t.revoked_at is None]) == 2
    assert (await get_refresh_token(connection, logged_out)).revoked_at == START


async def test_logout_without_cookies_returns_204_without_set_cookie(
    client: httpx2.AsyncClient,
) -> None:
    response = await log_out(client)

    assert response.status_code == 204
    assert "set-cookie" not in response.headers

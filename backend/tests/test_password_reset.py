from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common import clock
from app.config.settings import AppSettings, Environment, Settings, get_settings
from app.features.core.auth.endpoints.dependencies import get_email_sender
from app.features.core.auth.enums import VerificationPurpose
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.auth.services.verification_code_service import VerificationCodeService
from app.main import create_app
from app.model_registry import RefreshToken, User, VerificationCode

pytestmark = pytest.mark.anyio

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
EMAIL = "ada@example.com"
PASSWORD = "correct-horse"
NEW_PASSWORD = "battery-staple"
WRONG_PASSWORD = "wrong-horse"
AUTH = "/api/v1/auth"
RESET = f"{AUTH}/password-reset"


@dataclass
class SentEmail:
    to: str
    subject: str
    html: str
    text: str


@dataclass
class FakeEmailSender:
    sent: list[SentEmail] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        self.sent.append(SentEmail(to=to, subject=subject, html=html, text=text))


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
def generated_codes(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    def generate_in_order(*codes: str) -> None:
        sequence = iter(codes)
        monkeypatch.setattr(VerificationCodeService, "generate", lambda self: next(sequence))

    return generate_in_order


@pytest.fixture
def mailbox() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def environment() -> Environment:
    return "local"


@pytest.fixture
def app(mailbox: FakeEmailSender, environment: Environment) -> FastAPI:
    app = create_app()
    settings = Settings(app=AppSettings(environment=environment))
    app.dependency_overrides[get_settings] = lambda: settings
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
    """Registers and verifies Ada; verification starts a session that stays active in the DB."""
    code = await register(client)
    response = await client.post(f"{AUTH}/verify-email", json={"email": EMAIL, "code": code})
    assert response.status_code == 200, response.text
    client.cookies.clear()


async def request_reset(client: httpx2.AsyncClient, email: str = EMAIL) -> httpx2.Response:
    return await client.post(f"{RESET}/request", json={"email": email})


async def request_code(client: httpx2.AsyncClient) -> str:
    response = await request_reset(client)
    assert response.status_code == 202, response.text
    code: str = response.json()["debug_code"]
    return code


async def verify_code(client: httpx2.AsyncClient, code: str, email: str = EMAIL) -> httpx2.Response:
    return await client.post(f"{RESET}/verify-code", json={"email": email, "code": code})


def confirmation(code: str, **overrides: str) -> dict[str, str]:
    body = {
        "email": EMAIL,
        "code": code,
        "password": NEW_PASSWORD,
        "password_confirmation": NEW_PASSWORD,
    }
    body.update(overrides)
    return body


async def confirm(client: httpx2.AsyncClient, code: str, **overrides: str) -> httpx2.Response:
    return await client.post(f"{RESET}/confirm", json=confirmation(code, **overrides))


async def log_in(client: httpx2.AsyncClient, password: str) -> httpx2.Response:
    return await client.post(f"{AUTH}/login", json={"email": EMAIL, "password": password})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


async def get_user(connection: AsyncConnection) -> Any:
    return (await connection.execute(select(User).where(User.email == EMAIL))).one()


async def get_codes(connection: AsyncConnection, purpose: VerificationPurpose) -> list[Any]:
    user = await get_user(connection)
    result = await connection.execute(
        select(VerificationCode)
        .where(VerificationCode.user_id == user.id, VerificationCode.purpose == purpose)
        .order_by(VerificationCode.created_at)
    )
    return list(result.all())


async def get_reset_code(connection: AsyncConnection) -> Any:
    *_, latest = await get_codes(connection, VerificationPurpose.PASSWORD_RESET)
    return latest


async def get_refresh_tokens(connection: AsyncConnection) -> list[Any]:
    user = await get_user(connection)
    result = await connection.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    return list(result.all())


async def password_is(connection: AsyncConnection, password: str) -> bool:
    user = await get_user(connection)
    return await PasswordHasher().verify(password=password, password_hash=user.password_hash)


async def test_request_for_a_verified_user_emails_a_reset_code(
    client: httpx2.AsyncClient, mailbox: FakeEmailSender
) -> None:
    await create_verified_user(client)
    mailbox.sent.clear()

    response = await request_reset(client)

    assert response.status_code == 202
    code = response.json()["debug_code"]
    assert response.json() == {"debug_code": code}
    [email] = mailbox.sent
    assert email.to == EMAIL
    assert email.subject == "Reset your password"
    assert code in email.html
    assert code in email.text
    assert "/reset-password?" in email.text


async def test_request_for_an_unverified_user_emails_a_reset_code(
    client: httpx2.AsyncClient, mailbox: FakeEmailSender
) -> None:
    await register(client)
    mailbox.sent.clear()

    response = await request_reset(client)

    assert response.status_code == 202
    [email] = mailbox.sent
    assert email.subject == "Reset your password"


@pytest.mark.parametrize("environment", ["dev"])
async def test_deployed_environments_never_return_the_debug_code(
    client: httpx2.AsyncClient, mailbox: FakeEmailSender
) -> None:
    await client.post(
        f"{AUTH}/register",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": EMAIL,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )

    response = await request_reset(client)

    assert response.status_code == 202
    assert response.json() == {}
    assert mailbox.sent[-1].subject == "Reset your password"


async def test_request_too_soon_returns_429(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    await request_code(client)
    fake_clock.advance(seconds=59)

    response = await request_reset(client)

    assert response.status_code == 429
    assert response.json()["code"] == "RESEND_TOO_SOON"
    assert response.json()["retry_after"] == 1
    assert len(await get_codes(connection, VerificationPurpose.PASSWORD_RESET)) == 1


async def test_sixth_reset_code_within_an_hour_returns_429(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    for _ in range(5):
        assert (await request_reset(client)).status_code == 202
        fake_clock.advance(seconds=60)

    response = await request_reset(client)

    assert response.status_code == 429
    assert response.json()["code"] == "RESEND_TOO_SOON"
    assert response.json()["retry_after"] == 3600 - 300
    assert len(await get_codes(connection, VerificationPurpose.PASSWORD_RESET)) == 5


async def test_eleventh_reset_code_within_a_day_returns_429_until_the_oldest_leaves_the_window(
    client: httpx2.AsyncClient,
    connection: AsyncConnection,
    fake_clock: FakeClock,
    mailbox: FakeEmailSender,
) -> None:
    await create_verified_user(client)
    mailbox.sent.clear()
    # Four codes an hour stay under the hourly limit, so only the daily cap can refuse.
    for _ in range(10):
        assert (await request_reset(client)).status_code == 202
        fake_clock.advance(minutes=15)

    response = await request_reset(client)

    elapsed = 10 * 15 * 60
    assert response.status_code == 429
    assert response.json()["code"] == "RESEND_TOO_SOON"
    assert response.json()["retry_after"] == 24 * 3600 - elapsed
    assert response.headers["Retry-After"] == str(24 * 3600 - elapsed)
    assert len(await get_codes(connection, VerificationPurpose.PASSWORD_RESET)) == 10
    assert len(mailbox.sent) == 10

    fake_clock.advance(seconds=24 * 3600 - elapsed)
    assert (await request_reset(client)).status_code == 202


async def test_verification_codes_do_not_count_toward_reset_limits(
    client: httpx2.AsyncClient,
) -> None:
    await register(client)

    assert (await request_reset(client)).status_code == 202


@pytest.mark.parametrize("route", ["request", "verify-code", "confirm"])
async def test_unknown_email_returns_404(
    client: httpx2.AsyncClient, mailbox: FakeEmailSender, route: str
) -> None:
    body = confirmation("123456", email="nobody@example.com")

    response = await client.post(f"{RESET}/{route}", json=body)

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"
    assert mailbox.sent == []


async def test_verify_code_with_the_correct_code_does_not_consume_it(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    code = await request_code(client)

    response = await verify_code(client, code)

    assert response.status_code == 204
    reset_code = await get_reset_code(connection)
    assert reset_code.consumed_at is None
    assert reset_code.attempts == 0
    assert (await verify_code(client, code)).status_code == 204


async def test_verify_code_with_a_wrong_code_counts_the_attempt(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    code = await request_code(client)

    response = await verify_code(client, wrong(code))

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_INVALID"
    assert (await get_reset_code(connection)).attempts == 1


async def test_fifth_wrong_attempt_invalidates_the_reset_code(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    code = await request_code(client)
    for _ in range(5):
        assert (await verify_code(client, wrong(code))).status_code == 400

    assert (await verify_code(client, code)).status_code == 400
    response = await confirm(client, code)

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_INVALID"
    assert await password_is(connection, PASSWORD)


@pytest.mark.parametrize("route", ["verify-code", "confirm"])
async def test_expired_code_returns_code_expired(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock, route: str
) -> None:
    await create_verified_user(client)
    code = await request_code(client)
    fake_clock.advance(minutes=10)

    response = await client.post(f"{RESET}/{route}", json=confirmation(code))

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_EXPIRED"
    assert await password_is(connection, PASSWORD)


@pytest.mark.parametrize("route", ["verify-code", "confirm"])
async def test_no_reset_code_returns_code_invalid(
    client: httpx2.AsyncClient, connection: AsyncConnection, route: str
) -> None:
    await create_verified_user(client)

    response = await client.post(f"{RESET}/{route}", json=confirmation("123456"))

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_INVALID"


@pytest.mark.parametrize("route", ["verify-code", "confirm"])
async def test_an_email_verification_code_never_resets_the_password(
    client: httpx2.AsyncClient, connection: AsyncConnection, route: str
) -> None:
    verification_code = await register(client)

    response = await client.post(f"{RESET}/{route}", json=confirmation(verification_code))

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_INVALID"
    [stored] = await get_codes(connection, VerificationPurpose.EMAIL_VERIFICATION)
    assert stored.consumed_at is None
    assert stored.attempts == 0
    assert await get_codes(connection, VerificationPurpose.PASSWORD_RESET) == []
    user = await get_user(connection)
    assert user.email_verified_at is None
    assert await password_is(connection, PASSWORD)


async def test_confirm_sets_the_new_password_and_revokes_every_session(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    assert (await log_in(client, PASSWORD)).status_code == 200
    old_refresh_cookie = client.cookies["refresh_token"]
    code = await request_code(client)

    response = await confirm(client, code)

    assert response.status_code == 204
    assert response.headers.get_list("set-cookie") == []
    reset_code = await get_reset_code(connection)
    assert reset_code.consumed_at == START
    tokens = await get_refresh_tokens(connection)
    assert len(tokens) == 2
    assert all(token.revoked_at == START for token in tokens)

    client.cookies.clear()
    refresh = await client.post(
        f"{AUTH}/refresh", headers={"Cookie": f"refresh_token={old_refresh_cookie}"}
    )
    assert refresh.status_code == 401
    assert (await log_in(client, PASSWORD)).status_code == 401
    assert (await log_in(client, NEW_PASSWORD)).status_code == 200

    reuse = await confirm(client, code)
    assert reuse.status_code == 400
    assert reuse.json()["code"] == "CODE_INVALID"


async def test_access_token_issued_before_the_reset_stays_valid(
    client: httpx2.AsyncClient,
) -> None:
    await create_verified_user(client)
    assert (await log_in(client, PASSWORD)).status_code == 200
    code = await request_code(client)

    assert (await confirm(client, code)).status_code == 204

    assert (await client.get(f"{AUTH}/me")).status_code == 200


async def test_confirm_unlocks_a_locked_user(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    for _ in range(4):
        assert (await log_in(client, WRONG_PASSWORD)).status_code == 401
    assert (await log_in(client, WRONG_PASSWORD)).status_code == 423
    code = await request_code(client)

    response = await confirm(client, code)

    assert response.status_code == 204
    user = await get_user(connection)
    assert user.failed_login_attempts == 0
    assert user.login_locked_until is None
    assert (await log_in(client, NEW_PASSWORD)).status_code == 200


async def test_confirm_verifies_an_unverified_email(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await register(client)
    fake_clock.advance(minutes=1)
    code = await request_code(client)

    response = await confirm(client, code)

    assert response.status_code == 204
    user = await get_user(connection)
    assert user.email_verified_at == START + timedelta(minutes=1)
    assert (await log_in(client, NEW_PASSWORD)).status_code == 200


async def test_confirm_keeps_the_original_verification_time(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await create_verified_user(client)
    fake_clock.advance(minutes=1)
    code = await request_code(client)

    assert (await confirm(client, code)).status_code == 204

    assert (await get_user(connection)).email_verified_at == START


async def test_confirm_sets_a_password_for_a_user_without_one(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await connection.execute(
        insert(User).values(
            first_name="Ada", last_name="Lovelace", email=EMAIL, email_verified_at=START
        )
    )
    code = await request_code(client)

    response = await confirm(client, code)

    assert response.status_code == 204
    assert (await log_in(client, NEW_PASSWORD)).status_code == 200


async def test_confirm_with_a_wrong_code_counts_the_attempt(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    await create_verified_user(client)
    code = await request_code(client)

    response = await confirm(client, wrong(code))

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_INVALID"
    reset_code = await get_reset_code(connection)
    assert reset_code.attempts == 1
    assert reset_code.consumed_at is None
    assert await password_is(connection, PASSWORD)


async def test_a_new_reset_code_replaces_the_previous_one(
    client: httpx2.AsyncClient,
    connection: AsyncConnection,
    fake_clock: FakeClock,
    generated_codes: Callable[..., None],
) -> None:
    await create_verified_user(client)
    generated_codes("111111", "222222")
    await request_code(client)
    fake_clock.advance(seconds=60)
    await request_code(client)

    assert (await verify_code(client, "111111")).status_code == 400
    assert (await verify_code(client, "222222")).status_code == 204


@pytest.mark.parametrize(
    "overrides",
    [
        {"password_confirmation": "different-pass"},
        {"password": "short", "password_confirmation": "short"},
        {"password": "x" * 129, "password_confirmation": "x" * 129},
        {"code": "12345"},
        {"code": "abcdef"},
        {"email": "not-an-email"},
    ],
)
async def test_confirm_rejects_bad_input(
    client: httpx2.AsyncClient, overrides: dict[str, str]
) -> None:
    response = await client.post(f"{RESET}/confirm", json=confirmation("123456") | overrides)

    assert response.status_code == 422


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef"])
async def test_verify_code_rejects_a_malformed_code(client: httpx2.AsyncClient, code: str) -> None:
    assert (await verify_code(client, code)).status_code == 422

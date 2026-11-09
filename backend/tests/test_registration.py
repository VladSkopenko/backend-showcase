import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.common import clock
from app.config.settings import AppSettings, EmailSettings, Environment, Settings, get_settings
from app.features.core.auth.endpoints.dependencies import get_email_sender
from app.features.core.auth.services.password_hasher import PasswordHasher
from app.features.core.auth.services.verification_code_service import VerificationCodeService
from app.features.core.users.repositories import UserRepository
from app.main import create_app
from app.model_registry import User, VerificationCode

pytestmark = pytest.mark.anyio

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
PASSWORD = "correct-horse"


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
def app_settings(environment: Environment) -> Settings:
    return Settings(app=AppSettings(environment=environment))


@pytest.fixture
def app(mailbox: FakeEmailSender, app_settings: Settings) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: app_settings
    app.dependency_overrides[get_email_sender] = lambda: mailbox
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


def registration(**overrides: str) -> dict[str, str]:
    body = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
        "password": PASSWORD,
        "password_confirmation": PASSWORD,
    }
    body.update(overrides)
    return body


async def register(client: httpx2.AsyncClient, **overrides: str) -> dict[str, Any]:
    response = await client.post("/api/v1/auth/register", json=registration(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def verify(client: httpx2.AsyncClient, code: str, email: str = "ada@example.com") -> Any:
    return await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})


async def resend(client: httpx2.AsyncClient, email: str = "ada@example.com") -> Any:
    return await client.post("/api/v1/auth/resend-code", json={"email": email})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


async def get_user(connection: AsyncConnection, email: str = "ada@example.com") -> Any:
    return (await connection.execute(select(User).where(User.email == email))).one()


async def get_codes(connection: AsyncConnection, user_id: Any) -> list[Any]:
    result = await connection.execute(
        select(VerificationCode)
        .where(VerificationCode.user_id == user_id)
        .order_by(VerificationCode.created_at)
    )
    return list(result.all())


async def test_register_creates_an_unverified_user_and_emails_a_code(
    client: httpx2.AsyncClient, connection: AsyncConnection, mailbox: FakeEmailSender
) -> None:
    body = await register(client, email="  Ada@Example.COM ")

    assert set(body) == {"id", "email", "debug_code"}
    assert body["email"] == "ada@example.com"
    code = body["debug_code"]
    assert len(code) == 6 and code.isdigit()

    user = await get_user(connection)
    assert str(user.id) == body["id"]
    assert (user.first_name, user.last_name) == ("Ada", "Lovelace")
    assert user.email_verified_at is None
    assert user.password_hash != PASSWORD
    assert await PasswordHasher().verify(password=PASSWORD, password_hash=user.password_hash)

    [stored] = await get_codes(connection, user.id)
    assert stored.purpose.name == "EMAIL_VERIFICATION"
    assert stored.expires_at == START + timedelta(minutes=10)
    assert stored.attempts == 0
    assert stored.consumed_at is None

    [email] = mailbox.sent
    assert email.to == "ada@example.com"
    assert code in email.text
    assert code in email.html


async def test_register_with_the_email_of_a_verified_user_returns_409(
    client: httpx2.AsyncClient, mailbox: FakeEmailSender, fake_clock: FakeClock
) -> None:
    code = (await register(client))["debug_code"]
    assert (await verify(client, code)).status_code == 200
    fake_clock.advance(minutes=5)
    mailbox.sent.clear()

    response = await client.post(
        "/api/v1/auth/register", json=registration(email="ADA@example.com")
    )

    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_TAKEN"
    assert set(response.json()) == {"code", "message"}
    assert mailbox.sent == []


async def test_register_again_with_an_unverified_email_replaces_the_user(
    client: httpx2.AsyncClient,
    connection: AsyncConnection,
    fake_clock: FakeClock,
    mailbox: FakeEmailSender,
    generated_codes: Callable[..., None],
) -> None:
    generated_codes("111111", "222222")
    first = await register(client)
    fake_clock.advance(seconds=60)

    second = await register(
        client,
        first_name="Augusta",
        last_name="King",
        email="ADA@example.com",
        password="new-password",
        password_confirmation="new-password",
    )

    assert second == {"id": first["id"], "email": "ada@example.com", "debug_code": "222222"}
    user = await get_user(connection)
    assert (user.first_name, user.last_name) == ("Augusta", "King")
    assert await PasswordHasher().verify(password="new-password", password_hash=user.password_hash)
    assert len(await get_codes(connection, user.id)) == 2
    assert len(mailbox.sent) == 2
    assert "222222" in mailbox.sent[-1].text
    old = await verify(client, "111111")
    assert old.status_code == 400
    assert old.json()["code"] == "CODE_INVALID"
    assert (await verify(client, "222222")).status_code == 200


async def test_register_again_too_soon_returns_429_and_changes_nothing(
    client: httpx2.AsyncClient,
    connection: AsyncConnection,
    fake_clock: FakeClock,
    mailbox: FakeEmailSender,
) -> None:
    await register(client)
    fake_clock.advance(seconds=30)

    response = await client.post(
        "/api/v1/auth/register",
        json=registration(
            first_name="Augusta", password="new-password", password_confirmation="new-password"
        ),
    )

    assert response.status_code == 429
    assert response.json()["code"] == "RESEND_TOO_SOON"
    assert response.json()["retry_after"] == 30
    assert response.headers["Retry-After"] == "30"
    user = await get_user(connection)
    assert user.first_name == "Ada"
    assert await PasswordHasher().verify(password=PASSWORD, password_hash=user.password_hash)
    assert len(await get_codes(connection, user.id)) == 1
    assert len(mailbox.sent) == 1


@pytest.mark.parametrize("sixth_request", ["resend", "register"])
async def test_sixth_code_within_an_hour_returns_429_until_the_oldest_leaves_the_window(
    client: httpx2.AsyncClient,
    connection: AsyncConnection,
    fake_clock: FakeClock,
    mailbox: FakeEmailSender,
    sixth_request: str,
) -> None:
    await register(client)
    for _ in range(4):
        fake_clock.advance(seconds=60)
        assert (await resend(client)).status_code == 202
    fake_clock.advance(seconds=60)

    async def request_sixth_code() -> Any:
        if sixth_request == "resend":
            return await resend(client)
        return await client.post("/api/v1/auth/register", json=registration())

    response = await request_sixth_code()

    assert response.status_code == 429
    assert response.json()["code"] == "RESEND_TOO_SOON"
    assert response.json()["retry_after"] == 3600 - 300
    assert response.headers["Retry-After"] == str(3600 - 300)
    user = await get_user(connection)
    assert len(await get_codes(connection, user.id)) == 5
    assert len(mailbox.sent) == 5

    fake_clock.advance(seconds=3600 - 300)
    assert (await request_sixth_code()).status_code in (201, 202)
    assert len(await get_codes(connection, user.id)) == 6


async def test_the_daily_reset_cap_does_not_limit_verification_codes(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    await register(client)
    # Four codes an hour stay under the hourly limit, so only a daily cap could refuse.
    for _ in range(10):
        fake_clock.advance(minutes=15)
        assert (await resend(client)).status_code == 202

    user = await get_user(connection)
    assert len(await get_codes(connection, user.id)) == 11


async def test_register_maps_a_concurrent_unique_violation_to_email_taken(
    client: httpx2.AsyncClient, mailbox: FakeEmailSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    await register(client)
    mailbox.sent.clear()

    async def nobody(*args: Any, **kwargs: Any) -> None:
        return None

    # Simulates a parallel request that inserted the same email after this one's lookup.
    monkeypatch.setattr(UserRepository, "get_by_email", nobody)
    response = await client.post("/api/v1/auth/register", json=registration())

    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_TAKEN"
    assert mailbox.sent == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"password_confirmation": "different-pass"},
        {"password": "short", "password_confirmation": "short"},
        {"email": "not-an-email"},
        {"first_name": ""},
        {"last_name": "   "},
        {"first_name": "x" * 101},
        {"password": "p" * 129, "password_confirmation": "p" * 129},
    ],
    ids=[
        "passwords-differ",
        "short-password",
        "bad-email",
        "empty-first",
        "blank-last",
        "long-name",
        "long-password",
    ],
)
async def test_register_rejects_bad_input(
    client: httpx2.AsyncClient, mailbox: FakeEmailSender, overrides: dict[str, str]
) -> None:
    response = await client.post("/api/v1/auth/register", json=registration(**overrides))

    assert response.status_code == 422
    assert mailbox.sent == []


async def test_verify_with_the_correct_code_marks_the_email_verified(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    code = (await register(client))["debug_code"]
    fake_clock.advance(minutes=3)

    response = await verify(client, code, email="ADA@example.com")

    assert response.status_code == 200
    user = await get_user(connection)
    assert response.json() == {
        "id": str(user.id),
        "email": "ada@example.com",
        "email_verified_at": fake_clock.current.isoformat().replace("+00:00", "Z"),
    }
    assert user.email_verified_at == fake_clock.current
    [stored] = await get_codes(connection, user.id)
    assert stored.consumed_at == fake_clock.current
    set_cookies = response.headers.get_list("set-cookie")
    assert any(header.startswith("access_token=") for header in set_cookies)
    assert any(header.startswith("refresh_token=") for header in set_cookies)
    assert (await client.get("/api/v1/auth/me")).json()["id"] == str(user.id)


async def test_verify_with_a_wrong_code_counts_the_attempt(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    code = (await register(client))["debug_code"]

    response = await verify(client, wrong(code))

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_INVALID"
    assert "set-cookie" not in response.headers
    user = await get_user(connection)
    assert user.email_verified_at is None
    [stored] = await get_codes(connection, user.id)
    assert stored.attempts == 1


async def test_fifth_wrong_attempt_invalidates_the_code(
    client: httpx2.AsyncClient, connection: AsyncConnection
) -> None:
    code = (await register(client))["debug_code"]

    for _ in range(5):
        assert (await verify(client, wrong(code))).status_code == 400
    response = await verify(client, code)

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_INVALID"
    user = await get_user(connection)
    assert user.email_verified_at is None
    [stored] = await get_codes(connection, user.id)
    assert stored.attempts == 5


async def test_verify_after_ten_minutes_returns_code_expired(
    client: httpx2.AsyncClient, connection: AsyncConnection, fake_clock: FakeClock
) -> None:
    code = (await register(client))["debug_code"]
    fake_clock.advance(minutes=10, seconds=1)

    response = await verify(client, code)

    assert response.status_code == 400
    assert response.json()["code"] == "CODE_EXPIRED"
    assert (await get_user(connection)).email_verified_at is None


async def test_verify_and_resend_for_a_verified_email_return_409(
    client: httpx2.AsyncClient, fake_clock: FakeClock
) -> None:
    code = (await register(client))["debug_code"]
    assert (await verify(client, code)).status_code == 200
    fake_clock.advance(minutes=5)

    verify_again = await verify(client, code)
    resend_again = await resend(client)

    assert verify_again.status_code == 409
    assert verify_again.json()["code"] == "ALREADY_VERIFIED"
    assert resend_again.status_code == 409
    assert resend_again.json()["code"] == "ALREADY_VERIFIED"


async def test_resend_issues_a_new_code_and_invalidates_the_old_one(
    client: httpx2.AsyncClient,
    connection: AsyncConnection,
    fake_clock: FakeClock,
    mailbox: FakeEmailSender,
    generated_codes: Callable[..., None],
) -> None:
    generated_codes("111111", "222222")
    old_code = (await register(client))["debug_code"]
    assert old_code == "111111"
    fake_clock.advance(seconds=60)

    response = await resend(client, email="Ada@Example.com")

    assert response.status_code == 202
    new_code = response.json()["debug_code"]
    assert new_code == "222222"
    assert len(mailbox.sent) == 2
    assert new_code in mailbox.sent[-1].text
    user = await get_user(connection)
    assert len(await get_codes(connection, user.id)) == 2

    old = await verify(client, old_code)
    assert old.status_code == 400
    assert old.json()["code"] == "CODE_INVALID"
    assert (await verify(client, new_code)).status_code == 200


async def test_resend_too_soon_returns_429_with_retry_after(
    client: httpx2.AsyncClient, fake_clock: FakeClock, mailbox: FakeEmailSender
) -> None:
    await register(client)
    fake_clock.advance(seconds=20)

    response = await resend(client)

    assert response.status_code == 429
    assert response.json()["code"] == "RESEND_TOO_SOON"
    assert response.json()["retry_after"] == 40
    assert response.headers["Retry-After"] == "40"
    assert len(mailbox.sent) == 1


async def test_verify_and_resend_for_an_unknown_email_return_404(
    client: httpx2.AsyncClient,
) -> None:
    verify_response = await verify(client, "123456", email="nobody@example.com")
    resend_response = await resend(client, email="nobody@example.com")

    assert verify_response.status_code == 404
    assert verify_response.json()["code"] == "USER_NOT_FOUND"
    assert resend_response.status_code == 404
    assert resend_response.json()["code"] == "USER_NOT_FOUND"


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
async def test_deployed_environments_never_return_the_debug_code(
    client: httpx2.AsyncClient, fake_clock: FakeClock, mailbox: FakeEmailSender
) -> None:
    body = await register(client)
    fake_clock.advance(seconds=60)
    response = await resend(client)

    assert set(body) == {"id", "email"}
    assert response.status_code == 202
    assert "debug_code" not in response.json()
    assert len(mailbox.sent) == 2


@pytest.mark.parametrize("environment", ["local", "dev"])
async def test_unconfigured_email_is_logged_without_the_code(
    app: FastAPI,
    client: httpx2.AsyncClient,
    environment: str,
    caplog: pytest.LogCaptureFixture,
    generated_codes: Callable[..., None],
) -> None:
    # The test defaults leave email unconfigured.
    del app.dependency_overrides[get_email_sender]
    generated_codes("987654")

    with caplog.at_level(logging.WARNING):
        response = await client.post("/api/v1/auth/register", json=registration())

    assert response.status_code == 201
    records = [record for record in caplog.records if "ada@example.com" in record.getMessage()]
    assert records
    expected_level = logging.WARNING if environment == "local" else logging.ERROR
    assert all(record.levelno == expected_level for record in records)
    assert "987654" not in caplog.text


async def test_a_failing_email_send_is_logged_without_the_code(
    app: FastAPI,
    client: httpx2.AsyncClient,
    caplog: pytest.LogCaptureFixture,
    generated_codes: Callable[..., None],
) -> None:
    class FailingSender:
        async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
            raise ConnectionError("SMTP is down")

    app.dependency_overrides[get_email_sender] = FailingSender
    generated_codes("987654")

    with caplog.at_level(logging.WARNING):
        response = await client.post("/api/v1/auth/register", json=registration())

    assert response.status_code == 201
    assert any(record.levelno == logging.ERROR for record in caplog.records)
    assert "987654" not in caplog.text


@pytest.fixture
def smtp_settings() -> Settings:
    return Settings(
        email=EmailSettings(
            username="sender@gmail.com",
            password=SecretStr("app-password"),
            sender="sender@gmail.com",
        )
    )


async def test_configured_email_is_sent_over_smtp_with_starttls(
    app: FastAPI,
    client: httpx2.AsyncClient,
    smtp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_settings] = lambda: smtp_settings
    del app.dependency_overrides[get_email_sender]
    calls: list[tuple[EmailMessage, dict[str, Any]]] = []

    async def fake_send(message: EmailMessage, **kwargs: Any) -> None:
        calls.append((message, kwargs))

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    code = (await register(client))["debug_code"]

    [(message, kwargs)] = calls
    assert message["From"] == "sender@gmail.com"
    assert message["To"] == "ada@example.com"
    assert message["Subject"] == "Confirm your email"
    text_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    assert text_part is not None and html_part is not None
    assert code in text_part.get_content()
    assert code in html_part.get_content()
    assert kwargs["hostname"] == "smtp.gmail.com"
    assert kwargs["port"] == 587
    assert kwargs["start_tls"] is True
    assert kwargs["username"] == "sender@gmail.com"
    assert kwargs["password"] == "app-password"

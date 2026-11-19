import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from support.bookings import (
    ADA,
    GRACE,
    STAFF,
    START,
    TOMORROW,
    FakeClock,
    Venue,
    add_booking,
    add_guest,
    add_participant,
    assert_error,
    at,
    book,
    sign_in,
)

from app.config.settings import NotificationSettings, Settings, get_settings
from app.features.core.auth.endpoints.dependencies import get_email_sender
from app.features.core.bookings.enums import BookingStatus
from app.main import create_app
from app.model_registry import Booking, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

REQUESTS = "/api/v1/staff/booking-requests"
LINUS = "linus@family.test"
EVENING = at(TOMORROW, 19)


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


class FailingEmailSender:
    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        raise ConnectionError("SMTP is down")


@pytest.fixture
def mailbox() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def app(mailbox: FakeEmailSender) -> FastAPI:
    app = create_app()
    settings = Settings(notifications=NotificationSettings(skip_email_domains=[]))
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


class FirstFailingEmailSender:
    def __init__(self) -> None:
        self.attempted: list[str] = []
        self.sent: list[str] = []

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        self.attempted.append(to)
        if len(self.attempted) == 1:
            raise ConnectionError("SMTP is down")
        self.sent.append(to)


async def add_user(
    session_factory: async_sessionmaker[AsyncSession], *, email: str, first_name: str
) -> User:
    user = User(
        first_name=first_name,
        last_name="Tester",
        email=email,
        email_verified_at=START - timedelta(days=1),
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
    return user


@pytest.fixture
async def linus(session_factory: async_sessionmaker[AsyncSession]) -> User:
    return await add_user(session_factory, email=LINUS, first_name="Linus")


async def request(
    client: httpx2.AsyncClient, table_id: uuid.UUID, starts_at: datetime, party_size: int = 6
) -> str:
    response = await book(client, table_id, starts_at, party_size=party_size)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PENDING"
    booking_id: str = response.json()["id"]
    return booking_id


async def decide(client: httpx2.AsyncClient, booking_id: str | uuid.UUID, action: str) -> Any:
    return await client.post(f"{REQUESTS}/{booking_id}/{action}")


async def test_approving_emails_the_participants_and_the_rejected_competitors(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    linus: User,
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    approved = await request(client, venue.eight.id, EVENING, party_size=8)
    await add_participant(session_factory, booking_id=approved, user=linus)
    await sign_in(client, GRACE)
    await request(client, venue.eight.id, at(TOMORROW, 19, 30))
    await sign_in(client, STAFF)

    response = await decide(client, approved, "approve")

    assert response.status_code == 200, response.text
    assert sorted(email.to for email in mailbox.sent) == sorted([ADA, GRACE, LINUS])
    emails = {email.to: email for email in mailbox.sent}
    for address in (ADA, LINUS):
        email = emails[address]
        assert email.subject == "Your booking request is approved"
        for part in (email.text, email.html):
            assert "Friday, 13 November 2026" in part
            assert "19:00" in part
            assert venue.second.address in part
            assert "8 people" in part
            assert "https://family-rest.vercel.app/reservations" in part
    rejected = emails[GRACE]
    assert rejected.subject == "Your booking request is rejected"
    assert "19:30" in rejected.text
    assert "6 people" in rejected.text
    assert "https://family-rest.vercel.app/reservations" in rejected.text


async def test_an_approval_emails_each_rejected_request_once(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    linus: User,
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    margaret = await add_user(session_factory, email="margaret@family.test", first_name="Margaret")
    edsger = await add_user(session_factory, email="edsger@family.test", first_name="Edsger")
    await sign_in(client, ADA)
    approved = await request(client, venue.eight.id, EVENING, party_size=8)
    later = await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.eight,
        starts_at=at(TOMORROW, 19, 30),
        status=BookingStatus.PENDING,
        party_size=6,
    )
    await add_participant(session_factory, booking_id=later.id, user=linus)
    earlier = await add_booking(
        session_factory,
        user=margaret,
        table=venue.eight,
        starts_at=at(TOMORROW, 18),
        status=BookingStatus.PENDING,
        party_size=7,
    )
    await add_participant(session_factory, booking_id=earlier.id, user=edsger)
    await sign_in(client, STAFF)

    response = await decide(client, approved, "approve")

    assert response.status_code == 200, response.text
    assert sorted(email.to for email in mailbox.sent) == sorted(
        [ADA, GRACE, LINUS, margaret.email, edsger.email]
    )
    emails = {email.to: email for email in mailbox.sent}
    for address in (GRACE, LINUS):
        assert "19:30" in emails[address].text
        assert "6 people" in emails[address].text
    for address in (margaret.email, edsger.email):
        assert "18:00" in emails[address].text
        assert "7 people" in emails[address].text


@pytest.mark.parametrize("skip_email_domains", [None, [" @Example.com "]])
async def test_skipped_domains_are_matched_per_recipient(
    app: FastAPI,
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    linus: User,
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
    skip_email_domains: list[str] | None,
) -> None:
    settings = (
        Settings()
        if skip_email_domains is None
        else Settings(notifications=NotificationSettings(skip_email_domains=skip_email_domains))
    )
    app.dependency_overrides[get_settings] = lambda: settings
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await add_participant(session_factory, booking_id=pending, user=linus)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "reject")

    assert response.status_code == 200, response.text
    assert [email.to for email in mailbox.sent] == [LINUS]


async def test_one_failing_email_does_not_stop_the_others(
    app: FastAPI,
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    linus: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = FirstFailingEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    await sign_in(client, ADA)
    approved = await request(client, venue.eight.id, EVENING, party_size=8)
    await sign_in(client, GRACE)
    await request(client, venue.eight.id, at(TOMORROW, 19, 30))
    await sign_in(client, STAFF)

    response = await decide(client, approved, "approve")

    assert response.status_code == 200, response.text
    failed, *others = sender.attempted
    assert sorted(sender.attempted) == sorted([ADA, GRACE])
    assert sender.sent == others
    [record] = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert failed in record.getMessage()


async def test_names_are_escaped_in_the_html_email(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ann = await add_user(session_factory, email="ann@family.test", first_name="Ann<b>")
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await add_participant(session_factory, booking_id=pending, user=ann)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "reject")

    assert response.status_code == 200, response.text
    [email] = [email for email in mailbox.sent if email.to == ann.email]
    assert "Ann&lt;b&gt;" in email.html
    assert "<b>" not in email.html


async def test_rejecting_emails_only_participants_with_an_account(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    guest = await add_guest(session_factory, name="Alex", token="alex-token")
    await add_participant(session_factory, booking_id=pending, guest=guest)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "reject")

    assert response.status_code == 200, response.text
    assert [(email.to, email.subject) for email in mailbox.sent] == [
        (ADA, "Your booking request is rejected")
    ]


async def test_skipped_domains_get_no_email(
    app: FastAPI,
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    mailbox: FakeEmailSender,
) -> None:
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "reject")

    assert response.status_code == 200, response.text
    assert mailbox.sent == []


async def test_a_failing_email_keeps_the_decision(
    app: FastAPI,
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    connection: AsyncConnection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app.dependency_overrides[get_email_sender] = FailingEmailSender
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "approve")

    assert response.status_code == 200, response.text
    status = await connection.scalar(select(Booking.status).where(Booking.id == uuid.UUID(pending)))
    assert status == BookingStatus.CONFIRMED
    [record] = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert ADA in record.getMessage()
    assert record.exc_info is not None


async def test_a_failed_decision_emails_nobody(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    mailbox: FakeEmailSender,
    connection: AsyncConnection,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, GRACE)
    competitor = await request(client, venue.six.id, at(TOMORROW, 19, 30))
    await add_booking(
        session_factory,
        user=users[GRACE],
        table=venue.six,
        starts_at=at(TOMORROW, 18, 30),
        party_size=6,
    )
    await sign_in(client, STAFF)

    response = await decide(client, pending, "approve")

    assert_error(response, 409, "SLOT_UNAVAILABLE")
    assert mailbox.sent == []
    status = await connection.scalar(
        select(Booking.status).where(Booking.id == uuid.UUID(competitor))
    )
    assert status == BookingStatus.PENDING


async def test_the_notification_routes_are_gone(
    client: httpx2.AsyncClient, users: dict[str, User]
) -> None:
    await sign_in(client, ADA)

    assert (await client.get("/api/v1/notifications")).status_code == 404
    assert (await client.post(f"/api/v1/notifications/{uuid.uuid4()}/read")).status_code == 404

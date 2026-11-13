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
    TZ,
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
from app.features.core.notifications.enums import NotificationKind
from app.main import create_app
from app.model_registry import Booking, Notification, User

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("no_locations")]

NOTIFICATIONS = "/api/v1/notifications"
REQUESTS = "/api/v1/staff/booking-requests"
LINUS = "linus@family.test"
EVENING = at(TOMORROW, 19)
APPROVED = NotificationKind.BOOKING_REQUEST_APPROVED
REJECTED = NotificationKind.BOOKING_REQUEST_REJECTED


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
    # The shared fixture users live at example.com, which is skipped by default.
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


async def stored_notifications(
    connection: AsyncConnection,
) -> list[tuple[uuid.UUID, NotificationKind, uuid.UUID, datetime, datetime | None]]:
    rows = await connection.execute(
        select(
            Notification.user_id,
            Notification.kind,
            Notification.booking_id,
            Notification.created_at,
            Notification.read_at,
        )
    )
    return sorted((row[0], row[1], row[2], row[3], row[4]) for row in rows)


async def add_notification(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    booking: Booking,
    created_at: datetime,
    kind: NotificationKind = APPROVED,
    read_at: datetime | None = None,
) -> Notification:
    notification = Notification(
        user_id=user.id, kind=kind, booking_id=booking.id, created_at=created_at, read_at=read_at
    )
    async with session_factory() as session:
        session.add(notification)
        await session.commit()
    return notification


def notification_body(notification: Notification) -> dict[str, Any]:
    return {
        "id": str(notification.id),
        "kind": notification.kind.value,
        "booking_id": str(notification.booking_id),
        "created_at": notification.created_at.astimezone(TZ).isoformat(),
        "read_at": None
        if notification.read_at is None
        else notification.read_at.astimezone(TZ).isoformat(),
    }


async def test_approving_notifies_the_participants_and_the_rejected_competitors(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    linus: User,
    mailbox: FakeEmailSender,
    connection: AsyncConnection,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await sign_in(client, ADA)
    approved = await request(client, venue.eight.id, EVENING, party_size=8)
    await add_participant(session_factory, booking_id=approved, user=linus)
    await sign_in(client, GRACE)
    competitor = await request(client, venue.eight.id, at(TOMORROW, 19, 30))
    await sign_in(client, STAFF)

    response = await decide(client, approved, "approve")

    assert response.status_code == 200, response.text
    assert await stored_notifications(connection) == sorted(
        [
            (users[ADA].id, APPROVED, uuid.UUID(approved), START, None),
            (linus.id, APPROVED, uuid.UUID(approved), START, None),
            (users[GRACE].id, REJECTED, uuid.UUID(competitor), START, None),
        ]
    )
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


async def test_an_approval_notifies_each_rejected_request_once(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    linus: User,
    mailbox: FakeEmailSender,
    connection: AsyncConnection,
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
    assert await stored_notifications(connection) == sorted(
        [
            (users[ADA].id, APPROVED, uuid.UUID(approved), START, None),
            (users[GRACE].id, REJECTED, later.id, START, None),
            (linus.id, REJECTED, later.id, START, None),
            (margaret.id, REJECTED, earlier.id, START, None),
            (edsger.id, REJECTED, earlier.id, START, None),
        ]
    )
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
    connection: AsyncConnection,
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
    assert await stored_notifications(connection) == sorted(
        [
            (users[ADA].id, REJECTED, uuid.UUID(pending), START, None),
            (linus.id, REJECTED, uuid.UUID(pending), START, None),
        ]
    )
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


async def test_rejecting_notifies_only_participants_with_an_account(
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
    guest = await add_guest(session_factory, name="Alex", token="alex-token")
    await add_participant(session_factory, booking_id=pending, guest=guest)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "reject")

    assert response.status_code == 200, response.text
    assert await stored_notifications(connection) == [
        (users[ADA].id, REJECTED, uuid.UUID(pending), START, None)
    ]
    assert [(email.to, email.subject) for email in mailbox.sent] == [
        (ADA, "Your booking request is rejected")
    ]


async def test_skipped_domains_get_the_notification_but_no_email(
    app: FastAPI,
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    staff: User,
    mailbox: FakeEmailSender,
    connection: AsyncConnection,
) -> None:
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    await sign_in(client, ADA)
    pending = await request(client, venue.six.id, EVENING)
    await sign_in(client, STAFF)

    response = await decide(client, pending, "reject")

    assert response.status_code == 200, response.text
    assert await stored_notifications(connection) == [
        (users[ADA].id, REJECTED, uuid.UUID(pending), START, None)
    ]
    assert mailbox.sent == []


async def test_a_failing_email_keeps_the_decision_and_its_notifications(
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
    assert await stored_notifications(connection) == [
        (users[ADA].id, APPROVED, uuid.UUID(pending), START, None)
    ]
    [record] = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert ADA in record.getMessage()
    assert record.exc_info is not None


async def test_a_failed_decision_notifies_nobody(
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
    assert await stored_notifications(connection) == []
    assert mailbox.sent == []
    status = await connection.scalar(
        select(Booking.status).where(Booking.id == uuid.UUID(competitor))
    )
    assert status == BookingStatus.PENDING


async def test_users_list_their_own_notifications_newest_first(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=EVENING
    )
    oldest = await add_notification(
        session_factory,
        user=users[ADA],
        booking=booking,
        created_at=START - timedelta(hours=2),
        read_at=START - timedelta(hours=1),
    )
    middle = await add_notification(
        session_factory,
        user=users[ADA],
        booking=booking,
        created_at=START - timedelta(hours=1),
        kind=REJECTED,
    )
    newest = await add_notification(
        session_factory, user=users[ADA], booking=booking, created_at=START
    )
    await add_notification(session_factory, user=users[GRACE], booking=booking, created_at=START)
    await sign_in(client, ADA)

    response = await client.get(NOTIFICATIONS)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [notification_body(item) for item in (newest, middle, oldest)],
        "total": 3,
        "limit": 20,
        "offset": 0,
    }
    unread = await client.get(NOTIFICATIONS, params={"unread_only": "true"})
    assert unread.status_code == 200, unread.text
    assert [item["id"] for item in unread.json()["items"]] == [str(newest.id), str(middle.id)]
    assert unread.json()["total"] == 2
    page = await client.get(NOTIFICATIONS, params={"limit": 1, "offset": 1})
    assert page.status_code == 200, page.text
    assert [item["id"] for item in page.json()["items"]] == [str(middle.id)]
    assert (page.json()["total"], page.json()["limit"], page.json()["offset"]) == (3, 1, 1)
    assert (await client.get(NOTIFICATIONS, params={"limit": 50})).status_code == 200
    assert (await client.get(NOTIFICATIONS, params={"limit": 51})).status_code == 422
    assert (await client.get(NOTIFICATIONS, params={"offset": 2**63})).status_code == 422


async def test_marking_read_keeps_the_first_read_time(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    fake_clock: FakeClock,
    connection: AsyncConnection,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=EVENING
    )
    notification = await add_notification(
        session_factory, user=users[ADA], booking=booking, created_at=START - timedelta(hours=1)
    )
    await sign_in(client, ADA)

    first = await client.post(f"{NOTIFICATIONS}/{notification.id}/read")
    fake_clock.advance(minutes=5)
    second = await client.post(f"{NOTIFICATIONS}/{notification.id}/read")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    notification.read_at = START
    assert first.json() == notification_body(notification)
    assert second.json() == first.json()
    stored = await connection.scalar(
        select(Notification.read_at).where(Notification.id == notification.id)
    )
    assert stored == START


async def test_another_users_or_an_unknown_notification_is_not_found(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    connection: AsyncConnection,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=EVENING
    )
    foreign = await add_notification(
        session_factory, user=users[ADA], booking=booking, created_at=START
    )
    await sign_in(client, GRACE)

    assert_error(
        await client.post(f"{NOTIFICATIONS}/{foreign.id}/read"), 404, "NOTIFICATION_NOT_FOUND"
    )
    assert_error(
        await client.post(f"{NOTIFICATIONS}/{uuid.uuid4()}/read"), 404, "NOTIFICATION_NOT_FOUND"
    )
    stored = await connection.scalar(
        select(Notification.read_at).where(Notification.id == foreign.id)
    )
    assert stored is None


async def test_anonymous_callers_cannot_list_or_mark_read(
    client: httpx2.AsyncClient,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    booking = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=EVENING
    )
    notification = await add_notification(
        session_factory, user=users[ADA], booking=booking, created_at=START
    )

    assert_error(await client.get(NOTIFICATIONS), 401, "NOT_AUTHENTICATED")
    assert_error(
        await client.post(f"{NOTIFICATIONS}/{notification.id}/read"), 401, "NOT_AUTHENTICATED"
    )

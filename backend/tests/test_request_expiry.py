import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from support.bookings import (
    ADA,
    GRACE,
    START,
    FakeClock,
    Venue,
    add_booking,
    add_guest,
    add_participant,
    assert_error,
    cancel,
    edit,
    sign_in,
)

from app.config.settings import Settings, get_settings
from app.features.core.bookings.enums import BookingStatus, ParticipantRole
from app.features.core.notifications.enums import NotificationKind
from app.features.core.notifications.services.booking_decision_notifier import (
    BookingDecisionNotifier,
)
from app.infrastructure.background_tasks import PeriodicTask, RequestExpiryJob
from app.main import create_app
from app.model_registry import (
    Booking,
    BookingParticipant,
    DiningTable,
    Location,
    Notification,
    User,
)

pytestmark = pytest.mark.anyio

LINUS = "linus@family.test"
LEAD = timedelta(minutes=120)
REJECTED = NotificationKind.BOOKING_REQUEST_REJECTED
SUBJECT = "Your booking request is rejected"


@dataclass
class FakeEmailSender:
    sent: list[tuple[str, str]] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        self.sent.append((to, subject))


@pytest.fixture
def mailbox() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def job(
    session_factory: async_sessionmaker[AsyncSession],
    mailbox: FakeEmailSender,
    fake_clock: FakeClock,
) -> RequestExpiryJob:
    return RequestExpiryJob(session_factory, settings=Settings(), email_sender=mailbox)


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession], fake_clock: FakeClock
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.fixture
async def linus(session_factory: async_sessionmaker[AsyncSession]) -> User:
    user = User(
        first_name="Linus",
        last_name="Tester",
        email=LINUS,
        email_verified_at=START - timedelta(days=1),
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
    return user


async def pending_request(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    table: DiningTable,
    starts_at: datetime,
) -> Booking:
    return await add_booking(
        session_factory,
        user=user,
        table=table,
        starts_at=starts_at,
        status=BookingStatus.PENDING,
        party_size=6,
    )


async def stored_decision(
    connection: AsyncConnection, booking_id: uuid.UUID
) -> tuple[BookingStatus, datetime | None, uuid.UUID | None]:
    row = (
        await connection.execute(
            select(Booking.status, Booking.decided_at, Booking.decided_by_id).where(
                Booking.id == booking_id
            )
        )
    ).one()
    return row[0], row[1], row[2]


async def stored_notifications(
    connection: AsyncConnection,
) -> list[tuple[uuid.UUID, NotificationKind, uuid.UUID, datetime]]:
    rows = await connection.execute(
        select(
            Notification.user_id,
            Notification.kind,
            Notification.booking_id,
            Notification.created_at,
        )
    )
    return sorted((row[0], row[1], row[2], row[3]) for row in rows)


@pytest.mark.usefixtures("no_locations")
async def test_the_sweep_rejects_a_pending_request_inside_the_lead_and_notifies_it(
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    linus: User,
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    booking = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=START + timedelta(minutes=90)
    )
    await add_participant(session_factory, booking_id=booking.id, user=linus)

    await job.run()

    assert await stored_decision(connection, booking.id) == (BookingStatus.REJECTED, START, None)
    assert await stored_notifications(connection) == sorted(
        [
            (users[ADA].id, REJECTED, booking.id, START),
            (linus.id, REJECTED, booking.id, START),
        ]
    )
    # Ada lives at example.com, a skipped domain.
    assert mailbox.sent == [(LINUS, SUBJECT)]


@pytest.mark.usefixtures("no_locations")
async def test_the_sweep_leaves_later_requests_and_confirmed_bookings(
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    later = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=START + timedelta(hours=3)
    )
    confirmed = await add_booking(
        session_factory, user=users[ADA], table=venue.four, starts_at=START + timedelta(hours=1)
    )

    with caplog.at_level(logging.INFO):
        await job.run()

    assert await stored_decision(connection, later.id) == (BookingStatus.PENDING, None, None)
    assert await stored_decision(connection, confirmed.id) == (BookingStatus.CONFIRMED, None, None)
    assert await stored_notifications(connection) == []
    assert mailbox.sent == []
    assert not [r for r in caplog.records if r.name.startswith("app.infrastructure")]


@pytest.mark.usefixtures("no_locations")
async def test_the_sweep_rejects_a_request_starting_exactly_the_lead_away(
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    at_lead = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=START + LEAD
    )
    after_lead = await pending_request(
        session_factory,
        user=users[ADA],
        table=venue.eight,
        starts_at=START + LEAD + timedelta(minutes=1),
    )

    await job.run()

    assert await stored_decision(connection, at_lead.id) == (BookingStatus.REJECTED, START, None)
    assert await stored_decision(connection, after_lead.id) == (BookingStatus.PENDING, None, None)


async def test_the_sweep_skips_a_request_locked_by_a_concurrent_decision(
    engine: AsyncEngine, mailbox: FakeEmailSender, fake_clock: FakeClock
) -> None:
    # SKIP LOCKED needs a second transaction that sees the row, so this test commits its rows and
    # removes them afterwards instead of using the rolled-back test connection.
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    job = RequestExpiryJob(sessionmaker, settings=Settings(), email_sender=mailbox)
    location = Location(
        slug=f"locked-row-{uuid.uuid4().hex}",
        address="Locked Row Street",
        description="Locked row",
        image_key="locations/locked-row.jpg",
    )
    user = User(
        first_name="Linus",
        last_name="Tester",
        email=f"locked-{uuid.uuid4().hex}@family.test",
        email_verified_at=START - timedelta(days=1),
    )
    async with sessionmaker() as session:
        session.add_all([location, user])
        await session.flush()
        table = DiningTable(location_id=location.id, label="Table 1", capacity=6)
        session.add(table)
        await session.flush()
        booking = Booking(
            user_id=user.id,
            table_id=table.id,
            party_size=6,
            starts_at=START + timedelta(minutes=90),
            ends_at=START + timedelta(minutes=180),
            status=BookingStatus.PENDING,
        )
        session.add(booking)
        await session.flush()
        session.add(
            BookingParticipant(
                booking_id=booking.id, user_id=user.id, role=ParticipantRole.OWNER, created_at=START
            )
        )
        await session.commit()
    try:
        async with engine.connect() as staff_decision:
            await staff_decision.begin()
            await staff_decision.execute(
                select(Booking.id).where(Booking.id == booking.id).with_for_update()
            )

            await asyncio.wait_for(job.run(), timeout=10)

            async with engine.connect() as reader:
                assert await stored_decision(reader, booking.id) == (
                    BookingStatus.PENDING,
                    None,
                    None,
                )
            await staff_decision.rollback()

        await asyncio.wait_for(job.run(), timeout=10)

        async with engine.connect() as reader:
            assert await stored_decision(reader, booking.id) == (
                BookingStatus.REJECTED,
                START,
                None,
            )
        assert mailbox.sent == [(user.email, SUBJECT)]
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.execute(delete(Location).where(Location.id == location.id))


@pytest.mark.usefixtures("no_locations")
async def test_a_failing_run_is_rolled_back_and_logged_and_the_next_run_works(
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    booking = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=START + timedelta(minutes=90)
    )
    original_record = BookingDecisionNotifier.record
    calls: list[None] = []

    async def fail_once(self: BookingDecisionNotifier, **kwargs: Any) -> None:
        calls.append(None)
        if len(calls) == 1:
            raise ConnectionError("database went away")
        await original_record(self, **kwargs)

    monkeypatch.setattr(BookingDecisionNotifier, "record", fail_once)
    runs: list[None] = []
    second_run_done = asyncio.Event()

    async def run_twice() -> None:
        runs.append(None)
        if len(runs) > 2:
            # Holds the loop until stop, so no third run touches the shared test connection.
            await asyncio.Event().wait()
        try:
            await job.run()
        finally:
            if len(runs) == 2:
                second_run_done.set()

    task = PeriodicTask(name="request expiry", interval_seconds=0.01, job=run_twice)
    with caplog.at_level(logging.ERROR):
        task.start()
        await asyncio.wait_for(second_run_done.wait(), timeout=10)
        await task.stop()

    failures = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(failures) == 1
    assert failures[0].exc_info is not None
    assert "request expiry" in failures[0].getMessage()
    assert await stored_decision(connection, booking.id) == (BookingStatus.REJECTED, START, None)
    assert await stored_notifications(connection) == [(users[ADA].id, REJECTED, booking.id, START)]


@pytest.mark.usefixtures("no_locations")
async def test_the_sweep_rejects_a_request_whose_start_has_passed(
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    booking = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=START - timedelta(days=1)
    )

    await job.run()

    assert await stored_decision(connection, booking.id) == (BookingStatus.REJECTED, START, None)
    assert await stored_notifications(connection) == [(users[ADA].id, REJECTED, booking.id, START)]


@pytest.mark.usefixtures("no_locations")
async def test_one_run_notifies_each_owner_for_their_own_request(
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adas = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=START + timedelta(minutes=60)
    )
    graces = await pending_request(
        session_factory,
        user=users[GRACE],
        table=venue.eight,
        starts_at=START + timedelta(minutes=90),
    )

    with caplog.at_level(logging.INFO):
        await job.run()

    assert await stored_notifications(connection) == sorted(
        [
            (users[ADA].id, REJECTED, adas.id, START),
            (users[GRACE].id, REJECTED, graces.id, START),
        ]
    )
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.INFO] == [
        "Rejected 2 pending requests inside the auto-reject lead"
    ]


@pytest.mark.usefixtures("no_locations")
async def test_the_sweep_notifies_the_owner_but_not_an_accountless_guest(
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    mailbox: FakeEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    booking = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=START + timedelta(minutes=90)
    )
    guest = await add_guest(session_factory, name="Grace's friend", token="guest-token")
    await add_participant(session_factory, booking_id=booking.id, guest=guest)

    await job.run()

    assert await stored_decision(connection, booking.id) == (BookingStatus.REJECTED, START, None)
    assert await stored_notifications(connection) == [(users[ADA].id, REJECTED, booking.id, START)]
    assert mailbox.sent == []


@pytest.mark.usefixtures("no_locations")
async def test_the_owner_cannot_cancel_or_edit_a_request_the_sweep_rejected(
    client: httpx2.AsyncClient,
    job: RequestExpiryJob,
    venue: Venue,
    users: dict[str, User],
    session_factory: async_sessionmaker[AsyncSession],
    connection: AsyncConnection,
) -> None:
    starts_at = START + timedelta(minutes=90)
    booking = await pending_request(
        session_factory, user=users[ADA], table=venue.six, starts_at=starts_at
    )
    await job.run()
    await sign_in(client, ADA)

    assert_error(await cancel(client, booking.id), 409, "BOOKING_REJECTED")
    assert_error(await edit(client, booking.id, starts_at), 409, "BOOKING_REJECTED")
    assert await stored_decision(connection, booking.id) == (BookingStatus.REJECTED, START, None)


async def test_the_periodic_task_repeats_survives_failures_and_stops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[None] = []
    third_call = asyncio.Event()

    async def flaky_sweep() -> None:
        calls.append(None)
        if len(calls) == 3:
            third_call.set()
        if len(calls) == 1:
            raise RuntimeError("first run fails")

    task = PeriodicTask(name="fake sweep", interval_seconds=0.01, job=flaky_sweep)
    with caplog.at_level(logging.ERROR):
        task.start()
        await asyncio.wait_for(third_call.wait(), timeout=5)
        await task.stop()
    stopped_at = len(calls)
    await asyncio.sleep(0.05)

    assert len(calls) == stopped_at
    assert [record.getMessage() for record in caplog.records if record.exc_info] == [
        "Background task 'fake sweep' failed; the next run tries again"
    ]
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "fake sweep"]


async def test_the_app_lifespan_starts_and_stops_the_request_expiry_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def fake_run(self: RequestExpiryJob) -> None:
        started.set()

    monkeypatch.setattr(RequestExpiryJob, "run", fake_run)
    app = create_app()

    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), timeout=5)
        assert [t for t in asyncio.all_tasks() if t.get_name() == "request expiry"]

    assert not [t for t in asyncio.all_tasks() if t.get_name() == "request expiry"]

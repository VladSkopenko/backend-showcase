import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from support.migrations import run_revision

pytestmark = pytest.mark.anyio

DASHBOARDS = Path(__file__).resolve().parents[2] / "deploy" / "platform" / "grafana" / "dashboards"
GRAFANA_READER = "0021_add_grafana_reader_role.py"
ROLE = "grafana_reader"
DATA_SOURCE = {"type": "grafana-postgresql-datasource", "uid": "restaurant-dev"}
SHARED_TAG = "restaurant"

PANEL_TITLES = {
    "bookings": [
        "Bookings per day",
        "Heatmap weekday × start hour",
        "Lead time distribution",
        "Cancellation rate",
        "Occupancy per location",
    ],
    "dishes": [
        "Top dishes overall and per location",
        "Dish popularity by hour of day",
        "Category mix by lunch and dinner",
    ],
    "checks": [
        "Average check per booking and per person",
        "Check by category",
        "Check by location and weekday",
        "Revenue per day",
    ],
    "visitors": [
        "Party size distribution over time",
        "Regulars vs occasional",
        "Top visitors by bookings",
        "Repeat rate",
    ],
    "staff": [
        "Pending requests now",
        "Time to decision (median, p90)",
        "Approval rate",
        "Auto-rejected share",
        "Requests per day",
    ],
}
UIDS = sorted(PANEL_TITLES)
VARIABLES = {uid: ["location"] for uid in UIDS} | {"visitors": ["location", "regular_threshold"]}
DEFAULT_RANGES = {uid: {"from": "now-7d", "to": "now+14d"} for uid in UIDS} | {
    "staff": {"from": "now-7d", "to": "now"}
}

NOW = datetime.now(UTC)
TIME_RANGES = {
    "default": (NOW - timedelta(days=7), NOW + timedelta(days=14)),
    "empty": (datetime(2001, 1, 1, tzinfo=UTC), datetime(2001, 1, 8, tzinfo=UTC)),
}

# One booking of every kind the panels tell apart, inside the default range by start and by
# creation: a visit with a submitted pre-order, a cancellation, and requests that were approved,
# rejected by the competing approval, rejected by staff, rejected automatically and left pending.
SEED = """
WITH visitor AS (
    INSERT INTO users (first_name, last_name, email)
    VALUES ('Nino', 'Visitor', 'nino@example.com') RETURNING id
), staff AS (
    INSERT INTO users (first_name, last_name, email, is_staff)
    VALUES ('Sam', 'Waiter', 'sam@example.com', true) RETURNING id
), seat AS (
    SELECT id FROM dining_tables ORDER BY id LIMIT 1
), booked AS (
    INSERT INTO bookings (
        user_id, table_id, party_size, starts_at, ends_at, status,
        decided_at, decided_by_id, created_at, updated_at
    )
    SELECT visitor.id, seat.id, kind.party_size,
           lunch.starts_at + kind.starts_in,
           lunch.starts_at + kind.starts_in + interval '90 minutes',
           kind.status::booking_status,
           now() - kind.decided_ago,
           CASE WHEN kind.by_staff THEN staff.id END,
           now() - interval '2 hours', now() - interval '1 hour'
    FROM visitor, staff, seat,
        (
            SELECT date_trunc('day', now(), 'Asia/Tbilisi') + interval '13 hours' AS starts_at
        ) AS lunch,
        (VALUES
            (2, interval '1 day', 'CONFIRMED', NULL::interval, false),
            (3, interval '2 days', 'CANCELLED', NULL, false),
            (6, interval '3 days', 'CONFIRMED', interval '30 minutes', true),
            (5, interval '3 days', 'REJECTED', interval '30 minutes', true),
            (7, interval '4 days', 'REJECTED', interval '10 minutes', true),
            (8, interval '5 days', 'REJECTED', interval '5 minutes', false),
            (5, interval '6 days', 'PENDING', NULL, false)
        ) AS kind (party_size, starts_in, status, decided_ago, by_staff)
    RETURNING id, user_id, status, party_size
), seated AS (
    INSERT INTO booking_participants (booking_id, user_id, role, created_at)
    SELECT id, user_id, 'OWNER', now() FROM booked
    RETURNING id, booking_id
)
INSERT INTO preorder_items (
    participant_id, dish_id, quantity, state, submission_id, submitted_at, created_at, updated_at
)
SELECT seated.id, dish.id, 2, 'SUBMITTED', gen_random_uuid(), now(), now(), now()
FROM seated
JOIN booked ON booked.id = seated.booking_id AND booked.status = 'CONFIRMED',
LATERAL (SELECT id FROM dishes ORDER BY id LIMIT 3) AS dish
"""


def load(uid: str) -> dict[str, Any]:
    dashboard: dict[str, Any] = json.loads((DASHBOARDS / f"{uid}.json").read_text())
    return dashboard


def variables_of(dashboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {variable["name"]: variable for variable in dashboard["templating"]["list"]}


def panel_queries(dashboard: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (panel["title"], target["rawSql"])
        for panel in dashboard["panels"]
        for target in panel["targets"]
    ]


def expand(sql: str, *, time_range: tuple[datetime, datetime], variables: dict[str, str]) -> str:
    """Replaces what Grafana replaces before PostgreSQL sees the query."""
    time_from, time_to = (f"'{moment:%Y-%m-%dT%H:%M:%S.000Z}'" for moment in time_range)
    sql = re.sub(r"\$__timeFilter\(([^()]+)\)", rf"\1 BETWEEN {time_from} AND {time_to}", sql)
    sql = sql.replace("$__timeFrom()", time_from).replace("$__timeTo()", time_to)
    for name, value in variables.items():
        sql = re.sub(rf"\${name}\b", value, sql)
    assert "$" not in sql, f"A macro or variable the test does not know: {sql}"
    return sql


async def run(connection: AsyncConnection, *, source: str, sql: str) -> list[Any]:
    try:
        return list((await connection.exec_driver_sql(sql)).all())
    except DBAPIError as error:
        pytest.fail(f"{source}: {error.orig}\n{sql}")


async def variable_values(
    connection: AsyncConnection, *, uid: str, dashboard: dict[str, Any]
) -> dict[str, str]:
    """All options of a multi-value query variable, quoted as Grafana quotes them for SQL."""
    values = {}
    for name, variable in variables_of(dashboard).items():
        if variable["type"] == "query":
            rows = await run(connection, source=f"{uid}: variable {name}", sql=variable["query"])
            assert rows, f"{uid}: variable {name} has no options"
            values[name] = ", ".join(f"'{row._mapping['__value']}'" for row in rows)
        else:
            values[name] = str(variable["current"]["value"])
    return values


def test_the_directory_holds_exactly_the_five_dashboards() -> None:
    assert sorted(path.name for path in DASHBOARDS.iterdir()) == [f"{uid}.json" for uid in UIDS]


@pytest.mark.parametrize("uid", UIDS)
def test_a_dashboard_is_provisioned_read_only_in_the_restaurant_zone_and_range(uid: str) -> None:
    dashboard = load(uid)

    assert dashboard["uid"] == uid
    assert dashboard["editable"] is False
    assert dashboard["timezone"] == "Asia/Tbilisi"
    assert dashboard["time"] == DEFAULT_RANGES[uid]
    assert dashboard["tags"] == [SHARED_TAG]
    assert [(link["type"], link["tags"]) for link in dashboard["links"]] == [
        ("dashboards", [SHARED_TAG])
    ]


@pytest.mark.parametrize("uid", UIDS)
def test_a_dashboard_has_exactly_the_panels_of_the_spec(uid: str) -> None:
    titles = [panel["title"] for panel in load(uid)["panels"]]

    assert sorted(titles) == sorted(PANEL_TITLES[uid])


@pytest.mark.parametrize("uid", UIDS)
def test_a_dashboard_filters_by_location_with_all_locations_by_default(uid: str) -> None:
    variables = variables_of(load(uid))
    location = variables["location"]

    assert sorted(variables) == sorted(VARIABLES[uid])
    assert location["type"] == "query"
    assert location["datasource"] == DATA_SOURCE
    assert (location["multi"], location["includeAll"]) == (True, True)
    assert location["current"]["value"] == ["$__all"]


def test_the_regular_threshold_defaults_to_ten() -> None:
    threshold = variables_of(load("visitors"))["regular_threshold"]

    assert threshold["current"]["value"] == "10"


@pytest.mark.parametrize("uid", UIDS)
def test_every_panel_reads_the_dev_data_source_narrowed_by_location(uid: str) -> None:
    for panel in load(uid)["panels"]:
        assert panel["datasource"] == DATA_SOURCE, panel["title"]
        assert panel["targets"], panel["title"]
        for target in panel["targets"]:
            assert target["datasource"] == DATA_SOURCE, panel["title"]
            assert "$location" in target["rawSql"], panel["title"]


# The outer test transaction is rolled back afterwards, so neither the role nor the rows outlive
# a test.
@pytest.mark.parametrize("time_range", TIME_RANGES)
@pytest.mark.parametrize("uid", UIDS)
async def test_every_query_runs_as_the_reader_role(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch, uid: str, time_range: str
) -> None:
    dashboard = load(uid)
    await connection.exec_driver_sql(SEED)
    await run_revision(
        connection, monkeypatch, file_name=GRAFANA_READER, step="upgrade", environment="dev"
    )
    await connection.execute(text(f"SET LOCAL ROLE {ROLE}"))

    variables = await variable_values(connection, uid=uid, dashboard=dashboard)
    for title, raw_sql in panel_queries(dashboard):
        sql = expand(raw_sql, time_range=TIME_RANGES[time_range], variables=variables)
        await run(connection, source=f"{uid}: {title}", sql=sql)

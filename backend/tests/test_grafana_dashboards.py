import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from support.migrations import run_revision

from app.infrastructure.metrics import RouteTemplates
from app.main import ROUTERS

pytestmark = pytest.mark.anyio

PLATFORM = Path(__file__).resolve().parents[2] / "deploy" / "platform"
DASHBOARDS = PLATFORM / "grafana" / "dashboards"
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
DEFAULT_RANGES = {uid: {"from": "now-7d/d", "to": "now+14d/d"} for uid in UIDS} | {
    "staff": {"from": "now-7d/d", "to": "now/d"}
}
SHARED_DEFINITIONS = [("staff", "requests", 4), ("checks", "checks", 3)]
MATRIX_FIELDS = ("rowField", "columnField", "valueField")
EMPTY_WITHOUT_BOOKINGS = {
    "bookings": "Bookings per day",
    "dishes": "Top dishes overall and per location",
    "checks": "Revenue per day",
    "visitors": "Top visitors by bookings",
    "staff": "Requests per day",
}

API_UID = "api"
PROMETHEUS = {"type": "prometheus", "uid": "prometheus"}
PROMETHEUS_SOURCE = PLATFORM / "grafana" / "provisioning" / "datasources" / "prometheus.yaml"
REQUESTS_TITLE = "Requests per second by route"
ERROR_SHARE_TITLE = "5xx share"
LATENCY_TITLE = "Latency p50 and p95 by route"
STATUS_TITLE = "Responses by status"
API_PANEL_TITLES = [REQUESTS_TITLE, ERROR_SHARE_TITLE, LATENCY_TITLE, STATUS_TITLE]
ROUTES_WITHOUT_LATENCY = [
    "/health",
    "/api/v1/assistant/sessions/{session_id}/messages",
    "/api/v1/assistant/sessions/{session_id}/actions/{action_id}/apply",
]
API_MAX_DATA_POINTS = 500
SELECTOR = r'[A-Za-z_:][A-Za-z0-9_:]*\{(?:[^}"]|"(?:[^"\\]|\\.)*")*\}'
API_METRICS = {
    "http_requests_total",
    "http_requests_created",
    "http_request_duration_seconds_bucket",
    "http_request_duration_seconds_sum",
    "http_request_duration_seconds_count",
    "http_request_duration_seconds_created",
}

NOW = datetime.now(UTC)
TIME_RANGES = {
    "default": (NOW - timedelta(days=7), NOW + timedelta(days=14)),
    "empty": (datetime(2001, 1, 1, tzinfo=UTC), datetime(2001, 1, 8, tzinfo=UTC)),
}

LOCATIONS = ["all", "without bookings"]
SEEDED_LOCATION = "SELECT location_id FROM dining_tables ORDER BY id LIMIT 1"
SEEDED_DISH_PRICES = (
    "SELECT sum(price_cents) AS cents FROM (SELECT price_cents FROM dishes ORDER BY id LIMIT 3) d"
)

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
            (5, interval '6 days', 'PENDING', NULL, false),
            (6, interval '7 days', 'CANCELLED', NULL, false),
            (7, interval '8 days', 'CANCELLED', interval '20 minutes', true)
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
SELECT seated.id, dish.id, line.quantity, line.state::preorder_item_state,
       CASE WHEN line.state = 'SUBMITTED' THEN gen_random_uuid() END,
       CASE WHEN line.state = 'SUBMITTED' THEN now() END, now(), now()
FROM seated
JOIN booked ON booked.id = seated.booking_id
JOIN (VALUES
    ('CONFIRMED', 'SUBMITTED', 2, 3),
    ('CONFIRMED', 'DRAFT', 7, 1),
    ('CANCELLED', 'SUBMITTED', 5, 1)
) AS line (status, state, quantity, dishes) ON line.status = booked.status::text
CROSS JOIN LATERAL (SELECT id FROM dishes ORDER BY id LIMIT line.dishes) AS dish
"""


@dataclass(frozen=True)
class Result:
    columns: list[str]
    rows: list[Any]

    def column(self, name: str) -> list[Any]:
        return [row._mapping[name] for row in self.rows]

    def value(self, name: str) -> Any:
        (value,) = self.column(name)
        return value


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
    time_from, time_to = (f"'{moment:%Y-%m-%dT%H:%M:%S.000Z}'" for moment in time_range)
    sql = re.sub(r"\$__timeFilter\(([^()]+)\)", rf"\1 BETWEEN {time_from} AND {time_to}", sql)
    sql = sql.replace("$__timeFrom()", time_from).replace("$__timeTo()", time_to)
    for name, value in variables.items():
        sql = re.sub(rf"\${name}\b", value, sql)
    assert "$" not in sql, f"A macro or variable the test does not know: {sql}"
    return sql


def first_definition(sql: str) -> str:
    return sql[: sql.index("\n)")]


async def run(connection: AsyncConnection, *, source: str, sql: str) -> Result:
    try:
        result = await connection.exec_driver_sql(sql)
    except DBAPIError as error:
        pytest.fail(f"{source}: {error.orig}\n{sql}")
    return Result(columns=list(result.keys()), rows=list(result.all()))


async def variable_values(
    connection: AsyncConnection, *, uid: str, dashboard: dict[str, Any], locations: str
) -> dict[str, str]:
    seeded = (await run(connection, source="seeded location", sql=SEEDED_LOCATION)).rows[0][0]
    values = {}
    for name, variable in variables_of(dashboard).items():
        if variable["type"] == "query":
            result = await run(connection, source=f"{uid}: variable {name}", sql=variable["query"])
            options = result.column("__value")
            if locations == "without bookings":
                options = [option for option in options if option != seeded][:1]
            assert options, f"{uid}: variable {name} has no options"
            values[name] = ", ".join(f"'{option}'" for option in options)
        else:
            values[name] = str(variable["current"]["value"])
    return values


async def panel_results(
    reader: AsyncConnection, *, uid: str, time_range: str = "default", locations: str = "all"
) -> dict[str, Result]:
    dashboard = load(uid)
    variables = await variable_values(reader, uid=uid, dashboard=dashboard, locations=locations)
    return {
        title: await run(
            reader,
            source=f"{uid}: {title}",
            sql=expand(raw_sql, time_range=TIME_RANGES[time_range], variables=variables),
        )
        for title, raw_sql in panel_queries(dashboard)
    }


@pytest.fixture
async def reader(connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch) -> AsyncConnection:
    await connection.exec_driver_sql(SEED)
    await run_revision(
        connection, monkeypatch, file_name=GRAFANA_READER, step="upgrade", environment="dev"
    )
    await connection.execute(text(f"SET LOCAL ROLE {ROLE}"))
    await connection.execute(text("SET LOCAL statement_timeout = '5s'"))
    return connection


def test_the_directory_holds_the_five_sql_dashboards_and_the_api_dashboard() -> None:
    assert sorted(path.name for path in DASHBOARDS.glob("*.json")) == sorted(
        f"{uid}.json" for uid in [*UIDS, API_UID]
    )


def test_the_start_page_is_a_dashboard_in_the_directory_the_provider_reads() -> None:
    compose = (PLATFORM / "compose.yml").read_text()
    provider = (
        PLATFORM / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml"
    ).read_text()

    (home,) = re.findall(r"GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH:\s*(\S+)", compose)
    (mounted,) = re.findall(r"- \./grafana/dashboards:([^:\s]+)", compose)
    (provided,) = re.findall(r"^\s*path:\s*(\S+)", provider, flags=re.MULTILINE)

    assert str(PurePosixPath(home).parent) == mounted == provided
    assert PurePosixPath(home).name in [f"{uid}.json" for uid in UIDS]


@pytest.mark.parametrize("uid", UIDS)
def test_a_dashboard_is_provisioned_read_only_in_the_restaurant_zone_and_range(uid: str) -> None:
    dashboard = load(uid)

    assert dashboard["uid"] == uid
    assert dashboard["editable"] is False
    assert dashboard["timezone"] == "Asia/Tbilisi"
    assert dashboard["time"] == DEFAULT_RANGES[uid]
    assert dashboard["tags"] == [SHARED_TAG]
    assert [
        (link["type"], link["tags"], link["includeVars"], link["keepTime"])
        for link in dashboard["links"]
    ] == [("dashboards", [SHARED_TAG], True, False)]


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


def test_the_location_variable_is_the_same_on_every_dashboard() -> None:
    variables = [variables_of(load(uid))["location"] for uid in UIDS]

    assert all(variable == variables[0] for variable in variables)


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


@pytest.mark.parametrize(("uid", "name", "copies"), SHARED_DEFINITIONS)
def test_a_definition_shared_by_panels_is_the_same_in_each(
    uid: str, name: str, copies: int
) -> None:
    definitions = [
        first_definition(sql)
        for _, sql in panel_queries(load(uid))
        if sql.startswith(f"WITH {name} AS (")
    ]

    assert len(definitions) == copies
    assert len(set(definitions)) == 1


@pytest.mark.parametrize("locations", LOCATIONS)
@pytest.mark.parametrize("time_range", TIME_RANGES)
@pytest.mark.parametrize("uid", UIDS)
async def test_every_query_runs_as_the_reader_role(
    reader: AsyncConnection, uid: str, time_range: str, locations: str
) -> None:
    await panel_results(reader, uid=uid, time_range=time_range, locations=locations)


@pytest.mark.parametrize("uid", UIDS)
async def test_a_location_without_bookings_shows_nothing(reader: AsyncConnection, uid: str) -> None:
    title = EMPTY_WITHOUT_BOOKINGS[uid]

    everywhere = await panel_results(reader, uid=uid)
    elsewhere = await panel_results(reader, uid=uid, locations="without bookings")

    assert everywhere[title].rows
    assert elsewhere[title].rows == []


@pytest.mark.parametrize("uid", UIDS)
async def test_panels_refer_to_columns_their_queries_return(
    reader: AsyncConnection, uid: str
) -> None:
    addresses = await run(reader, source="addresses", sql="SELECT address FROM locations")
    results = await panel_results(reader, uid=uid)

    for panel in load(uid)["panels"]:
        columns = set(results[panel["title"]].columns)
        transformations = panel.get("transformations", [])
        matched = [
            override["matcher"]["options"]
            for override in panel["fieldConfig"]["overrides"]
            if override["matcher"]["id"] == "byName"
        ]
        assert [step["id"] for step in transformations] in ([], ["groupingToMatrix"]), panel[
            "title"
        ]
        for step in transformations:
            assert {step["options"][field] for field in MATRIX_FIELDS} <= columns, panel["title"]
        if any(step["options"]["columnField"] == "location" for step in transformations):
            assert sorted(matched) == sorted(addresses.column("address")), panel["title"]
        else:
            assert set(matched) <= columns, panel["title"]


async def test_a_request_withdrawn_while_pending_is_not_a_cancelled_booking(
    reader: AsyncConnection,
) -> None:
    results = await panel_results(reader, uid="bookings")

    assert sum(results["Bookings per day"].column("Confirmed")) == 2
    assert sum(results["Bookings per day"].column("Cancelled")) == 2
    assert results["Cancellation rate"].value("Cancellation rate") == pytest.approx(1 / 2)


async def test_checks_count_only_the_submitted_items_of_visits(reader: AsyncConnection) -> None:
    prices = await run(reader, source="dish prices", sql=SEEDED_DISH_PRICES)
    check = 2 * prices.value("cents") / 100

    results = await panel_results(reader, uid="checks")
    average = results["Average check per booking and per person"]

    assert results["Revenue per day"].column("Revenue") == [pytest.approx(check)] * 2
    assert average.value("Per booking") == pytest.approx(check)
    assert average.value("Per person") == pytest.approx((check / 2 + check / 6) / 2)


async def test_the_staff_panels_tell_the_outcomes_of_requests_apart(
    reader: AsyncConnection,
) -> None:
    results = await panel_results(reader, uid="staff")
    (per_day,) = results["Requests per day"].rows

    assert {name: count for name, count in per_day._mapping.items() if name != "time"} == {
        "Approved": 2,
        "Rejected by staff": 1,
        "Lost to another request": 1,
        "Auto-rejected": 1,
        "Pending": 1,
        "Cancelled before a decision": 1,
    }
    assert results["Approval rate"].value("Approval rate") == pytest.approx(2 / 3)
    assert results["Auto-rejected share"].value("Auto-rejected share") == pytest.approx(1 / 5)
    assert results["Pending requests now"].value("Pending") == 1


def api_targets(*titles: str) -> list[tuple[str, str]]:
    return [
        (panel["title"], target["expr"])
        for panel in load(API_UID)["panels"]
        if not titles or panel["title"] in titles
        for target in panel["targets"]
    ]


def bare(expr: str) -> str:
    without_literals = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expr)
    return re.sub(r"\s+", "", without_literals)


def test_the_api_dashboard_is_provisioned_read_only_next_to_the_restaurant_dashboards() -> None:
    dashboard = load(API_UID)

    assert dashboard["uid"] == API_UID
    assert dashboard["editable"] is False
    assert dashboard["timezone"] == "Asia/Tbilisi"
    assert dashboard["time"] == {"from": "now-3h", "to": "now"}
    assert dashboard["refresh"] == "30s"
    assert dashboard["tags"] == [SHARED_TAG]
    assert [
        (link["type"], link["tags"], link["includeVars"], link["keepTime"])
        for link in dashboard["links"]
    ] == [("dashboards", [SHARED_TAG], True, False)]


def test_the_api_dashboard_has_exactly_its_four_panels() -> None:
    titles = [panel["title"] for panel in load(API_UID)["panels"]]

    assert sorted(titles) == sorted(API_PANEL_TITLES)


def test_the_api_dashboard_reads_only_prometheus() -> None:
    dashboard = load(API_UID)

    assert {
        json.dumps(source, sort_keys=True)
        for panel in dashboard["panels"]
        for source in [panel["datasource"], *(target["datasource"] for target in panel["targets"])]
    } == {json.dumps(PROMETHEUS, sort_keys=True)}
    assert variables_of(dashboard)["env"]["datasource"] == PROMETHEUS


def test_the_env_variable_lists_the_environments_with_dev_by_default() -> None:
    variables = variables_of(load(API_UID))
    env = variables["env"]
    query = env["query"]["query"] if isinstance(env["query"], dict) else env["query"]

    assert sorted(variables) == ["env"]
    assert bare(query) == "label_values(http_requests_total,env)"
    assert env["current"]["value"] == "dev"


def test_every_api_panel_pins_the_data_points_the_query_limit_was_sized_on() -> None:
    assert {panel.get("maxDataPoints") for panel in load(API_UID)["panels"]} == {
        API_MAX_DATA_POINTS
    }


def test_every_api_selector_reads_the_chosen_environment() -> None:
    assert api_targets()
    for title, expr in api_targets():
        selectors = re.findall(SELECTOR, expr)

        assert selectors, title
        for selector in selectors:
            assert 'env="$env"' in selector, (title, selector)


def test_every_api_range_selector_is_the_rate_interval() -> None:
    for title, expr in api_targets():
        windows = re.findall(r"\[([^\]]*)\]", bare(expr))

        assert windows, title
        assert set(windows) == {"$__rate_interval"}, title


def test_api_targets_read_only_the_api_metrics() -> None:
    for title, expr in api_targets():
        metrics = set(re.findall(r"([A-Za-z_:][A-Za-z0-9_:]*)\{", bare(expr)))

        assert metrics, title
        assert metrics <= API_METRICS, title


def test_the_latency_panel_shows_p50_and_p95_by_route_without_health_and_the_streams() -> None:
    expressions = [expr for _, expr in api_targets(LATENCY_TITLE)]

    assert len(expressions) == 2
    assert "histogram_quantile(0.5," in bare(expressions[0])
    assert "histogram_quantile(0.95," in bare(expressions[1])
    for expr in expressions:
        assert "by(le,route)" in bare(expr)
        for route in ROUTES_WITHOUT_LATENCY:
            assert f'route!="{route}"' in expr


def test_the_routes_left_out_of_latency_are_routes_the_api_serves() -> None:
    assert set(ROUTES_WITHOUT_LATENCY) <= RouteTemplates(ROUTERS).templates


def test_rate_and_status_panels_count_every_route() -> None:
    targets = api_targets(REQUESTS_TITLE, ERROR_SHARE_TITLE, STATUS_TITLE)

    assert targets
    for title, expr in targets:
        assert not re.search(r"route\s*(!=|!~|=~)", expr), title


def test_the_5xx_share_is_zero_rather_than_empty_without_errors() -> None:
    ((_, expr),) = api_targets(ERROR_SHARE_TITLE)

    assert 'status=~"5.."' in expr
    assert "orvector(0))/" in bare(expr)


def test_the_prometheus_data_source_is_provisioned_read_only_and_not_default() -> None:
    source = PROMETHEUS_SOURCE.read_text()
    lines = source.splitlines()
    (json_data,) = [index for index, line in enumerate(lines) if line.strip() == "jsonData:"]
    indent = len(lines[json_data]) - len(lines[json_data].lstrip())
    nested = []
    for line in lines[json_data + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        nested.append(line.strip())

    for key, value in [
        ("uid", "prometheus"),
        ("type", "prometheus"),
        ("access", "proxy"),
        ("url", "http://prometheus:9090"),
        ("isDefault", "false"),
        ("editable", "false"),
    ]:
        assert re.search(rf"^\s+-?\s*{key}:\s*{re.escape(value)}\s*(#.*)?$", source, re.MULTILINE)
    assert "timeInterval: 15s" in nested


def test_prometheus_bounds_every_query_within_its_memory_limit() -> None:
    compose = (PLATFORM / "compose.yml").read_text()
    (service,) = re.findall(
        r"^  prometheus:\n(.*?)(?=^  \S|^\S)", compose, re.MULTILINE | re.DOTALL
    )

    assert re.search(r"^\s+mem_limit: 512m$", service, re.MULTILINE)
    for flag in ["--query.timeout=10s", "--query.max-concurrency=4", "--query.max-samples=1000000"]:
        assert f"- {flag}\n" in service


def test_node_exporter_runs_only_the_collectors_the_dashboard_needs() -> None:
    compose = (PLATFORM / "compose.yml").read_text()
    (service,) = re.findall(
        r"^  node-exporter:\n(.*?)(?=^  \S|^\S)", compose, re.MULTILINE | re.DOTALL
    )
    flags = set(re.findall(r"^\s+- (--[a-z.-]+)", service, re.MULTILINE))

    assert {flag for flag in flags if flag.startswith("--collector.")} == {
        "--collector.disable-defaults",
        "--collector.cpu",
        "--collector.meminfo",
        "--collector.loadavg",
        "--collector.filesystem",
        "--collector.diskstats",
    }
    assert "--web.disable-exporter-metrics" in flags

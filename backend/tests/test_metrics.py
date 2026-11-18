import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2
import pytest
from fastapi import APIRouter, FastAPI
from prometheus_client import CollectorRegistry
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.types import Message, Receive, Scope, Send

from app.features.core.health.endpoints.dependencies import get_database_engine
from app.infrastructure.background_tasks import CleanupJob, PeriodicTask, RequestExpiryJob
from app.infrastructure.metrics import RequestMetricsMiddleware, RouteTemplates
from app.main import ROUTERS, create_app

pytestmark = pytest.mark.anyio

REQUESTS = "http_requests_total"
DURATION_COUNT = "http_request_duration_seconds_count"
STREAM_TEMPLATE = "/api/v1/assistant/sessions/{session_id}/messages"


def total(registry: CollectorRegistry, sample_name: str) -> float:
    return sum(
        sample.value
        for metric in registry.collect()
        for sample in metric.samples
        if sample.name == sample_name
    )


def assert_counted_once(
    registry: CollectorRegistry, *, method: str, route: str, status: str
) -> None:
    assert (
        registry.get_sample_value(REQUESTS, {"method": method, "route": route, "status": status})
        == 1
    )
    assert registry.get_sample_value(DURATION_COUNT, {"method": method, "route": route}) == 1
    assert total(registry, REQUESTS) == 1
    assert total(registry, DURATION_COUNT) == 1


@pytest.fixture
def app(engine: AsyncEngine) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_database_engine] = lambda: engine
    return app


@pytest.fixture
def registry(app: FastAPI) -> CollectorRegistry:
    registry: CollectorRegistry = app.state.metrics_registry
    return registry


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.mark.parametrize(
    ("path", "route", "status"),
    [
        ("/api/v1/menu/dishes", "/api/v1/menu/dishes", "200"),
        (f"/api/v1/bookings/{uuid.uuid4()}", "/api/v1/bookings/{booking_id}", "401"),
        ("/health", "/health", "200"),
        ("/nope", "unmatched", "404"),
        ("/docs", "unmatched", "200"),
        ("/metrics", "unmatched", "404"),
    ],
)
async def test_a_request_is_counted_once_by_method_route_template_and_status(
    client: httpx2.AsyncClient, registry: CollectorRegistry, path: str, route: str, status: str
) -> None:
    response = await client.get(path)

    assert str(response.status_code) == status
    assert_counted_once(registry, method="GET", route=route, status=status)


async def test_the_raw_path_never_becomes_a_label(
    client: httpx2.AsyncClient, registry: CollectorRegistry
) -> None:
    booking_id = uuid.uuid4()

    await client.get(f"/api/v1/bookings/{booking_id}", params={"secret": "value"})

    labels = [
        value
        for metric in registry.collect()
        for sample in metric.samples
        for value in sample.labels.values()
    ]
    assert not [value for value in labels if str(booking_id) in value or "secret" in value]


def test_the_template_table_covers_exactly_the_documented_paths() -> None:
    app = create_app()

    assert RouteTemplates(ROUTERS).templates == set(app.openapi()["paths"])


def test_each_app_has_its_own_registry() -> None:
    assert create_app().state.metrics_registry is not create_app().state.metrics_registry


def stream_router() -> APIRouter:
    router = APIRouter(prefix="/assistant")

    @router.post("/sessions/{session_id}/messages")
    async def stream() -> None: ...

    return router


def middleware_over(
    inner: Callable[[Scope, Receive, Send], Any],
) -> tuple[RequestMetricsMiddleware, CollectorRegistry]:
    router = stream_router()
    [route] = router.routes

    async def stub(scope: Scope, receive: Receive, send: Send) -> None:
        scope["route"] = route
        await inner(scope, receive, send)

    registry = CollectorRegistry()
    middleware = RequestMetricsMiddleware(
        stub, registry=registry, route_templates=RouteTemplates([(router, "/api/v1")])
    )
    return middleware, registry


def http_scope(method: str = "POST") -> Scope:
    return {
        "type": "http",
        "method": method,
        "path": f"/api/v1/assistant/sessions/{uuid.uuid4()}/messages",
        "headers": [],
        "query_string": b"",
    }


async def disconnected() -> Message:
    return {"type": "http.disconnect"}


async def ignore(message: Message) -> None:
    return None


async def test_an_error_before_the_response_starts_is_counted_as_500_and_reraised() -> None:
    error = RuntimeError("handler failed")

    async def raise_before_start(scope: Scope, receive: Receive, send: Send) -> None:
        raise error

    middleware, registry = middleware_over(raise_before_start)

    with pytest.raises(RuntimeError) as raised:
        await middleware(http_scope(), disconnected, ignore)

    assert raised.value is error
    assert_counted_once(registry, method="POST", route=STREAM_TEMPLATE, status="500")


async def test_a_stream_that_fails_after_starting_is_counted_once_with_the_started_status() -> None:
    async def fail_mid_stream(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
        raise RuntimeError("stream broke")

    middleware, registry = middleware_over(fail_mid_stream)

    with pytest.raises(RuntimeError, match="stream broke"):
        await middleware(http_scope(), disconnected, ignore)

    assert_counted_once(registry, method="POST", route=STREAM_TEMPLATE, status="200")


async def test_a_stream_the_client_leaves_is_counted_once_with_the_started_status() -> None:
    async def stream_until_disconnect(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
        assert (await receive())["type"] == "http.disconnect"

    middleware, registry = middleware_over(stream_until_disconnect)

    await middleware(http_scope(), disconnected, ignore)

    assert_counted_once(registry, method="POST", route=STREAM_TEMPLATE, status="200")


async def test_a_made_up_method_is_counted_as_other() -> None:
    async def answer(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 405, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware, registry = middleware_over(answer)

    await middleware(http_scope("RANDOM123"), disconnected, ignore)

    assert_counted_once(registry, method="other", route=STREAM_TEMPLATE, status="405")


async def test_a_lifespan_scope_passes_through_unchanged_and_is_not_counted() -> None:
    seen: list[tuple[Scope, Receive, Send]] = []

    async def record(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append((scope, receive, send))

    registry = CollectorRegistry()
    middleware = RequestMetricsMiddleware(
        record, registry=registry, route_templates=RouteTemplates([(stream_router(), "/api/v1")])
    )
    scope: Scope = {"type": "lifespan"}

    await middleware(scope, disconnected, ignore)

    assert seen == [(scope, disconnected, ignore)]
    assert seen[0][0] is scope
    assert scope == {"type": "lifespan"}
    assert total(registry, REQUESTS) == 0
    assert total(registry, DURATION_COUNT) == 0


@pytest.fixture
def idle_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def idle(self: object) -> None:
        return None

    monkeypatch.setattr(CleanupJob, "run", idle)
    monkeypatch.setattr(RequestExpiryJob, "run", idle)


async def port_answers(port: int) -> bool:
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        return False
    writer.close()
    await writer.wait_closed()
    return True


@pytest.mark.usefixtures("idle_jobs")
async def test_the_metrics_port_serves_the_series_while_the_app_runs_and_closes_after() -> None:
    app = create_app()

    async with app.router.lifespan_context(app):
        port: int = app.state.metrics_server.port
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
            assert (await client.get("/nope")).status_code == 404
        async with httpx2.AsyncClient() as metrics_client:
            response = await metrics_client.get(f"http://127.0.0.1:{port}/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert (
            'http_requests_total{method="GET",route="unmatched",status="404"} 1.0' in response.text
        )
        assert (
            'http_request_duration_seconds_count{method="GET",route="unmatched"} 1.0'
            in response.text
        )

    assert not await port_answers(port)


@pytest.mark.usefixtures("idle_jobs")
async def test_a_failed_startup_still_closes_the_metrics_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    def fail_to_start(self: PeriodicTask) -> None:
        raise RuntimeError("task failed to start")

    monkeypatch.setattr(PeriodicTask, "start", fail_to_start)

    with pytest.raises(RuntimeError, match="task failed to start"):
        async with app.router.lifespan_context(app):
            pass

    assert not await port_answers(app.state.metrics_server.port)

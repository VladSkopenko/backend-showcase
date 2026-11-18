---
title: 'The API serves request metrics on a private port'
type: 'feature'
created: '2026-11-18'
status: 'done'
baseline_commit: '57a10add5b9c88988bd3517a3374f6c47c581db9'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-api-metrics/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-api-metrics/gotchas.md'
  - '{project-root}/docs/adr/0007-single-vm-platform-and-app-stacks.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The API exposes nothing about its own traffic, so neither Prometheus (story 2) nor the public Grafana (story 3) has request rate, errors or latency to show.

**Approach:** Count every HTTP request with `prometheus-client` by method, full route template and status, observe its duration, and serve the metrics on a separate port (ADR 7) that the lifespan opens and closes. Port 8000 gains nothing.

## Boundaries & Constraints

**Always:** Metrics: `http_requests_total{method,route,status}` and `http_request_duration_seconds{method,route}` with the library's default buckets. `route` is the full template, e.g. `/api/v1/bookings/{booking_id}`; a request no API route handled is `route="unmatched"`: unknown paths and FastAPI's docs pages, which are plain Starlette routes and set no `scope["route"]`. The template comes from an explicit table built in `create_app` from the same (router, prefix) list that includes the routers (Vlad's decision 2026-11-18: option a, not FastAPI's native OpenTelemetry). `METRICS_PORT` (default 9000) is the only new setting. One registry per app instance. Duration and count are recorded once per request in `finally`.

**Never:** No `/metrics` route on the main app. No `env` label (Prometheus adds it in story 2). No user ids, raw paths or query strings in labels. No process or platform collectors, no exporters, no compose or deploy changes (story 2). No reliance on FastAPI private names (`_IncludedRouter`, effective route context).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Counted request | `GET /api/v1/menu/dishes` → 200 | counter `{GET,/api/v1/menu/dishes,200}` +1, one duration sample | N/A |
| Path parameter | `GET /api/v1/bookings/<uuid>` | `route="/api/v1/bookings/{booking_id}"` | N/A |
| Route without prefix | `GET /health` | `route="/health"` | N/A |
| Unknown path | `GET /nope` → 404 | `route="unmatched"`, `status="404"` | N/A |
| Docs page | `GET /docs` → 200 | `route="unmatched"`, `status="200"` | N/A |
| Unhandled error | handler raises before a response starts | counted with `status="500"` | exception re-raised unchanged |
| Streamed answer | SSE route, stream ends or client leaves | counted once with the started status | N/A |
| Main port | `GET /metrics` on the app | 404, counted as `unmatched` | N/A |
| Metrics port | `GET :METRICS_PORT/metrics` | Prometheus text format with the series above | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/main.py` -- `create_app` calls `app.include_router` eleven times (health without prefix, the rest at `/api/v1`); turn this into one (router, prefix) tuple list used both for including and for the template table. `lifespan` starts/stops periodic tasks: start the metrics server before them, stop it in `finally`. The `Exception` handler runs in `ServerErrorMiddleware`, outside user middleware: the metrics middleware sees the raw exception with no `http.response.start`.
- Verified 2026-11-18 on FastAPI 0.162: for an included router, `scope["route"]` is the original `APIRoute` (same object as in `router.routes`) whose `.path` lacks the include prefix (`/bookings/{booking_id}`). No feature router includes another router, so prefix + `route.path` is the full template; the table's 46 templates equal `app.openapi()["paths"]`. `app.routes` holds only the 4 docs `Route`s and private `_IncludedRouter`s, so tests compare against the OpenAPI paths, not `app.routes`.
- Path ids are UUIDs (`booking_id: uuid.UUID`): a non-UUID id answers 422.
- `backend/src/app/features/assistant/endpoints/assistant.py:122,235` -- the two `EventStreamResponse` routes.
- `backend/src/app/config/settings.py` -- one `BaseSettings` class per prefix composed into `Settings`; add `MetricsSettings` (`METRICS_`).
- `backend/tests/conftest.py:33,53-66` -- sets env at import and strips known prefixes per test: add `METRICS_` and set `METRICS_PORT=0` at import, so no test binds 9000. `tests/test_cleanup.py:493-514` runs the lifespan.
- `backend/pyproject.toml` -- `filterwarnings = ["error"]`: an unclosed socket fails the suite. `start_http_server` in 0.26.0 returns `(httpd, thread)` and never closes the socket: stop with `shutdown()`, `server_close()`, `thread.join()`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/conftest.py` -- `METRICS_PORT=0` at import, `METRICS_` among stripped prefixes -- isolation before any new test.
- [x] `backend/tests/test_metrics.py` -- failing tests for every matrix row: routing rows through the real app; the unhandled-error and streamed rows against the middleware over a stub ASGI app (raises before `http.response.start` → one `status="500"` and re-raise; sends start 200, then raises or sees `http.disconnect` → one `status="200"`). The template table's values equal `set(app.openapi()["paths"])`. Inside the lifespan, `app.state.metrics_server.port` answers `/metrics`; after it, the port is closed and no warning is raised -- tests first.
- [x] `backend/tests/test_settings.py` -- `METRICS_PORT` default 9000 and override.
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- `prometheus-client>=0.26.0` via `uv add`.
- [x] `backend/src/app/infrastructure/metrics/` -- classes: route template table, pure ASGI middleware (not `BaseHTTPMiddleware`, which buffers streaming), metrics server over `start_http_server(port, registry=...)` exposing the bound `port` (`httpd.server_port`).
- [x] `backend/src/app/config/settings.py` -- `MetricsSettings` with `port: int = 9000`.
- [x] `backend/src/app/main.py` -- router list, registry per app on `app.state`, metrics middleware added last (outermost). Lifespan: start the metrics server first and keep it on `app.state.metrics_server`, then wrap all later startup and the `yield` in `try/finally`, stopping it last, so a failed task start cannot leak the socket.
- [x] `backend/.env.example` -- `METRICS_PORT` with a one-line note.

**Acceptance Criteria:**
- Given the app started with its lifespan, when the metrics port is requested, then the series of the matrix are served there and nowhere on port 8000.
- Given the lifespan ends, when the port is probed, then it is closed and no warning is raised.
- Given a new router added to the list, when the suite runs, then its routes get full templates without other changes, and a router included outside the list fails the OpenAPI-paths test.

## Implementation Notes

- Package `app.infrastructure.metrics`: `RouteTemplates` (route object and template per `id`, matched with `is`), `RequestMetricsMiddleware` (methods outside GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS are labelled `other`, found in review), `MetricsServer`.
- Full suite must run alone: a parallel `pytest` from another worktree recreates `app_test` and fails this suite with `connection is closed`.
- Checks 2026-11-18: 938 passed; ruff, format, mypy, lint-imports clean. Live on 8010 with `METRICS_PORT=9010`: menu 200, booking 401 as `/api/v1/bookings/{booking_id}`, `/nope` and `:8010/metrics` 404 and `/docs` 200 as `unmatched`, `-X RANDOM123` as `other`; both ports closed after SIGTERM.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Evidence | Route |
|---|-------|---------|---------|----------|-------|
| 1 | edge, blind | `method` label taken raw from the request, unbounded | medium | Reproduced live on 8010: `-X RANDOM123 /nope` and `-X ZZZ /health` each created a series; uvicorn runs h11 (no httptools), which accepts any token; breaks the frozen "labels bounded" rule | patch |
| 2 | edge, blind | CancelledError or a disconnect with no response counted as 500 | low | Real only when a request is cancelled before any response; rare in everyday use and the fix adds a branch | reject |
| 3 | edge, blind | `METRICS_PORT` not range-validated | low | Out-of-range value fails loudly at bind on startup; nobody sets it; the fix adds a guard nobody asked for | reject |
| 4 | edge, blind | Metrics server binds 0.0.0.0, also on a developer's LAN | low | True, by library default and documented in gotchas.md; the series hold only counters; no named harm | reject |
| 5 | edge, blind | A failed `cleanup.start()` leaves request expiry running and the engine undisposed | low | Pre-existing order; `PeriodicTask.start` is only `asyncio.create_task` (periodic_task.py:19) and does not fail in practice | reject |
| 6 | edge | Default buckets end at 10 s, SSE turns land in +Inf | low | True, but the spec chose default buckets and story 3 leaves both SSE routes out of latency; the fix edits the spec | reject |
| 7 | edge | A nested router or `include_in_schema=False` route would be unmatched | low | No router nests another and none hides from the schema today; the OpenAPI-paths test fails loudly if that changes | reject |
| 8 | blind | `RouteTemplates` keys by `id(route)` and relies on routers outside to keep routes alive | low | Safe for the module-level `ROUTERS`; storing the route next to its template and comparing with `is` keeps the invariant inside the class, a direct correction | patch |
| 9 | blind | The non-http scope branch of the middleware has no test | low | Tests enter the lifespan via `lifespan_context`, bypassing the ASGI stack, so a broken branch would only show under uvicorn; one test closes it | patch |
| 10 | blind | `total_requests` and `total_durations` duplicate each other | low | Same body, different sample name; merge into one helper | patch |
| 11 | blind | `client` fixture takes an unused `session_factory` | false | Same pattern as `tests/test_menu.py:76-77`, where the fixture prepares the database | reject |
| 12 | verification-gap | No verification gaps | n/a | 16 tests ran and passed per the layer | n/a |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- all green
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- clean

**Manual checks (if no CLI):**
- Live: API on port 8010 with `METRICS_PORT=9010`; curl `/health`, `/api/v1/menu/dishes`, `/api/v1/bookings/00000000-0000-0000-0000-000000000001` (401), `/nope`, `/docs`, `:8010/metrics`; then `curl :9010/metrics` shows each with the right labels and `:8010/metrics` is 404.

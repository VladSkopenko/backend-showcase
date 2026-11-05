---
title: 'Health reports the database, and the root says the service works'
type: 'feature'
created: '2026-11-05'
status: 'done'
baseline_commit: '8ed8533cba850ba0c08d0901794294c7e823ac55'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `/health` answers `ok` even when PostgreSQL is down, so the deploy gate and the alerts cannot tell a working API from one that cannot reach its database.

**Approach:** Decision (Vlad, 2026-11-05): `/health` shows whether the app and the database work: it runs `SELECT 1` with a short timeout and answers 503 when the database is unavailable. Vlad's uncommitted `GET /` with `RootResponse` ships in the same change as it is.

## Boundaries & Constraints

**Always:**
- `GET /health` → 200 `{"status": "ok", "database": "ok"}` when `SELECT 1` succeeds; 503 `{"status": "error", "database": "unavailable"}` when the connection or query fails or exceeds the timeout. `HealthResponse.status: Literal["ok", "error"]`, `database: Literal["ok", "unavailable"]`.
- Timeout in settings: `DatabaseSettings.probe_timeout_seconds: float = 1.0` (`DATABASE_PROBE_TIMEOUT_SECONDS`); it must stay under the 2-second `HEALTHCHECK` timeout in `backend/Dockerfile`.
- Layers per ADR 11 and backend.md: the route maps `HealthService.check()` to the response; `HealthService` (class, constructor-injected engine and timeout) builds `DatabaseProbeRepository(engine)` whose `ping()` opens its own connection and runs `SELECT 1`. A failed probe is returned as a result (`HealthReport` dto), not raised.
- The probe never uses the request session from `get_session`: after a failed query that session needs a rollback, and `get_session` would commit and turn the 503 into a 500.
- The engine reaches the service through an endpoint provider wrapping `app.common.database.get_engine`, so tests can override it.
- `GET /` stays exactly as Vlad wrote it: 200 `{"message": "<APP_NAME> works"}`.

**Never:** detailed diagnostics in the body (error text, host, version), retries, a separate readiness endpoint, changes to the Dockerfile healthcheck, compose or alerting.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Healthy | database reachable | 200 `{"status": "ok", "database": "ok"}` | N/A |
| Database down | connection refused | 503 `{"status": "error", "database": "unavailable"}` | error caught in the service |
| Database slow | ping exceeds `probe_timeout_seconds` | 503 `{"status": "error", "database": "unavailable"}` within the timeout | N/A |
| Root | any state | 200 `{"message": "backend-showcase works"}` | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/health/endpoints/health.py`, `schemas/health.py` -- Vlad's `GET /` and `RootResponse` (uncommitted, keep); `health()` returns a fixed `ok` today.
- `backend/src/app/common/database.py` -- cached `get_engine()`; `get_session` commits after the handler.
- `backend/src/app/config/settings.py` -- `DatabaseSettings` gains `probe_timeout_seconds`.
- `backend/Dockerfile:28` -- `HEALTHCHECK` (`--timeout=3s`) uses `urllib.request.urlopen(..., timeout=2)`, which raises `HTTPError` on 503, so the container turns unhealthy and `compose up --wait` fails the deploy.
- `backend/tests/test_health.py` -- sync `TestClient(create_app())`; the OpenAPI test asserts `status` const `ok`, which changes to the two-value enum.
- `backend/tests/conftest.py` -- `engine` fixture (NullPool, `get_settings().database.url`; this change lands before the separate test database).

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_health.py` -- async tests with `httpx2.AsyncClient` and `ASGITransport`; healthy case overrides the engine provider with the `engine` fixture; down case with an engine on a closed port (`127.0.0.1:1`); slow case overrides the service provider with `HealthService(engine=..., timeout_seconds=0.05)` and `DatabaseProbeRepository.ping` patched to sleep longer; root and OpenAPI (`status` enum `ok`/`error`, `database` enum, `responses["503"]` present) tests.
- [x] `backend/tests/test_settings.py` -- `DATABASE_PROBE_TIMEOUT_SECONDS` mapping and default.
- [x] `backend/src/app/config/settings.py` -- `probe_timeout_seconds`.
- [x] `backend/src/app/features/core/health/repositories/database_probe_repository.py` (+ `__init__.py`) -- `DatabaseProbeRepository(engine).ping()`.
- [x] `backend/src/app/features/core/health/dto/health_report.py` (+ `__init__.py`) -- `HealthReport(database_ok: bool)`.
- [x] `backend/src/app/features/core/health/services/health_service.py` (+ `__init__.py`) -- timeout with `asyncio.timeout` (not `anyio.fail_after`: its cancel scope also cancels SQLAlchemy's shielded close and logs an ERROR per timed-out probe, reproduced on SQLAlchemy 2.1.8); catches `TimeoutError`, `sqlalchemy.exc.SQLAlchemyError` (bad credentials), `OSError` (connection refused, unknown host).
- [x] `backend/src/app/features/core/health/endpoints/dependencies.py`, `health.py`, `schemas/health.py` -- engine and service providers; the route keeps returning `HealthResponse` and sets 503 through an injected `response: Response` (`response.status_code = 503`), so `response_model` still validates; `responses={503: {"model": HealthResponse}}` documents it.
- [x] `backend/.env.example` -- `DATABASE_PROBE_TIMEOUT_SECONDS=1`.

**Acceptance Criteria:**
- Given uvicorn started with `DATABASE_PORT=1` (nothing listens there; the developer's database keeps running), when `GET /health` runs, then it answers 503 with `database: unavailable` within the timeout; with the normal port, 200.
- Given CI, then lint, mypy, import-linter and tests pass.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.

## Implementation Notes

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | `anyio.fail_after` logs an ERROR when it cancels a slow query | medium | Reproduced: `Exception terminating connection` with anyio, clean with `asyncio.timeout`. Patched Tasks. |
| 2 | spec review | Returning `JSONResponse(503)` skips `response_model` and leaves 503 out of OpenAPI | medium | Patched: injected `response.status_code`, `responses={503: ...}`. |
| 3 | spec review | No way to pass a small timeout to the slow-case test | low | Patched: test overrides the service provider. |
| 4 | spec review | `probe_timeout_seconds` accepts 0, negative or over 2 | low | Operator misconfiguration only (registration row 3, login row 31). Rejected. |
| 5 | verification-gap, blind | `SQLAlchemyError` branch (bad credentials) untested | medium | Port 1 raises `OSError`; dropping `SQLAlchemyError` stays green. Patch: wrong-password test. |
| 6 | verification-gap, blind | Slow-case test bypasses the provider and never cancels a real query | medium | Hardcoding the timeout or reverting to `anyio.fail_after` stays green. Patch: settings override, real `pg_sleep`, no ERROR in `caplog`. |
| 7 | blind | A failed probe leaves no log line | low | 503 causes cannot be told apart. Defer: not in the spec (workflow.md rule 3); logged with the other log items for Phase 4. |
| 8 | blind | Comments name a "2-second HEALTHCHECK timeout"; Docker's is 3 s, the 2 s is `urlopen` | low | Dockerfile:27-28. Patch: reword. |
| 9 | blind | Closing a timed-out connection to a hung server can add up to 2 s (`close(timeout=2)`) | low | asyncpg.py:940. Only on an established connection to a frozen server; the healthcheck still turns unhealthy, only the body is lost. Rejected. |
| 10 | blind | No ADR for `/health` now depending on the database (deploy gate, rollback, alerts) | low | workflow.md rule 5. Defer with the auth ADR batch. |
| 11 | blind, edge | Probe shares the app pool; exhaustion reports a healthy database as unavailable | low | The deploy gate runs on a fresh container without traffic; an unhealthy container is not restarted. Rejected. |
| 12 | edge | `probe_timeout_seconds` accepts 0, negative, nan or over 2 | low | carried: row 4. Rejected. |
| 13 | edge | An untranslated asyncpg error at connect returns 500 | maybe-false | SQLAlchemy wraps asyncpg errors in `DBAPIError` (bad password verified); no untranslated case shown. Rejected as low if true. |
| 14 | edge | Down-case test assumes a local host refuses port 1 | low | Tests run against the local server only. Rejected. |

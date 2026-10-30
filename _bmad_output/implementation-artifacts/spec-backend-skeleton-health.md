---
title: 'Backend skeleton with a health endpoint'
type: 'feature'
created: '2026-10-28'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '60b42f8c8cc7bebe97d880e490db554e09e6710a'
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/.claude/rules/backend.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** There is no backend code yet. The DevOps phase needs a runnable API with a health endpoint, so it can build an image and gate deploys on it.

**Approach:** Create a minimal uv project in `backend/` with a src layout and the package `app`. It contains a FastAPI app whose only router is `GET /health`, settings behind a cached `get_settings()`, and a test written before the code. The structure follows ADR 11.

## Boundaries & Constraints

**Always:**
- The package is `app` under `backend/src/`. Imports are `from app...`, never `from src.app...`.
- Dependencies are managed by uv, with Python 3.14 and a committed `uv.lock`.
- Directories are created together with their first file. Every package directory under `src/app/` has an `__init__.py`; `tests/` has none.
- Settings are read only through `get_settings()`.

**Never:**
- No database, SQLAlchemy, Alembic or Redis. They come after the DevOps phase.
- No Dockerfile, compose, pre-commit config or CI workflows. Those are Vlad's.
- No empty or placeholder directories (`common/`, `infrastructure/`, `static/` and so on).
- No database check in `/health` in this story.
- No `uv init`: it generates `src/backend/`, a `README.md` and `.python-version`, none of which belong here.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_PATH | `GET /health` on a running app | `200`, JSON body `{"status": "ok"}` | N/A |

</frozen-after-approval>

## Code Map

- `backend/.gitkeep` -- existing placeholder, the only file in `backend/`. Leave it.
- `docs/adr/0011-feature-sliced-backend-layout.md` -- target layout and import rules. Health is a `core` feature.
- `.claude/rules/backend.md` -- loads for `backend/**`. Its Structure section applies here.
- `README.md` "Planned layout" -- currently shows `backend/app/`. Update it to `backend/src/app/`. The "Tests" row in Planned stack names `httpx`; change it to `httpx2`.
- `CLAUDE.md` "Commands" -- says commands get filled in as phases land. Add the backend commands.

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml` and `backend/src/app/__init__.py` -- write `pyproject.toml` by hand, not with `uv init`:
  - `name = "backend"`, `version = "0.1.0"`, `requires-python = ">=3.14"`;
  - build backend `uv_build>=0.13.6,<0.14`, with `[tool.uv.build-backend] module-name = "app"`;
  - add dependencies with `uv add fastapi uvicorn pydantic pydantic-settings` and `uv add --dev pytest httpx2 ruff mypy`, so bounds are `>=`;
  - config: ruff `target-version = "py314"`, `line-length = 100`, `lint.select = ["E", "W", "F", "I", "B", "UP"]`; mypy `strict = true`; pytest `testpaths = ["tests"]`;
  - create an empty `src/app/__init__.py`;
  - `uv lock` produces `uv.lock`.

  -- `app` must be importable before the test can fail for the right reason.
- [x] `backend/tests/test_health.py` -- test with `fastapi.testclient.TestClient` on `create_app()`: `GET /health` returns 200 and `{"status": "ok"}`. Run it. The expected red is `ModuleNotFoundError: No module named 'app.main'`. -- tests first.
- [x] `backend/src/app/config/__init__.py` and `config/settings.py` -- empty `__init__.py`. `Settings(BaseSettings)` with `app_name: str = "backend-showcase"`, and `get_settings()` wrapped in `functools.lru_cache`. -- tests can override settings later.
- [x] `backend/src/app/features/__init__.py`, `features/core/__init__.py`, `features/core/health/__init__.py` -- empty package markers.
- [x] `backend/src/app/features/core/health/schemas/health.py` and `schemas/__init__.py` -- `HealthResponse(BaseModel)` with `status: Literal["ok"]`. The `__init__` re-exports it with `__all__ = ["HealthResponse"]`. -- typed OpenAPI for the frontend's client generator, and the same layout pattern as endpoints.
- [x] `backend/src/app/features/core/health/endpoints/health.py` and `endpoints/__init__.py` -- `APIRouter` with `GET /health` and `response_model=HealthResponse`. The `__init__` re-exports `router` with `__all__ = ["router"]`. -- `mypy --strict` has no implicit re-export.
- [x] `backend/src/app/main.py` -- `create_app()` builds `FastAPI(title=get_settings().app_name)` and includes the health router. A module-level `app = create_app()` serves uvicorn. -- one place that wires routers.
- [x] `README.md` -- Planned layout: `backend/src/app/`, with `migrations/`, `tests/`, `Dockerfile` and `pyproject.toml` under `backend/`. In Planned stack, `httpx` becomes `httpx2`. -- docs match the code.
- [x] `CLAUDE.md` -- Commands section: run, test, lint and type-check commands from `backend/`. -- agents and humans use the same commands.

**Acceptance Criteria:**
- Given a fresh clone, when `uv sync` and then `uv run pytest` run in `backend/`, then all tests pass with no warnings.
- Given the code, when `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy src tests` run in `backend/`, then all of them report no issues.
- Given `uv run uvicorn app.main:app` is running, when `curl -i localhost:8000/health` is sent, then the response is `200` with `{"status":"ok"}`.
- Given the running app, when `/openapi.json` is fetched, then `/health` is listed with the `HealthResponse` schema.

## Implementation Notes

- Implemented by a fresh-context subagent from this spec; verified independently against the diff since `baseline_commit`.
- Red step observed: `ModuleNotFoundError: No module named 'app.main'`.
- Resolved versions: fastapi 0.162.0, pydantic 2.14.1, pydantic-settings 2.16.2, uvicorn 0.54.0; dev: httpx2 2.16.0, mypy 2.4.1, pytest 9.2.0, ruff 0.17.3.
- `uv run pytest -W error` passes, confirming `httpx2` removes the Starlette deprecation warning (triage #3).
- Live check: `GET /health` → `200 {"status":"ok"}`; OpenAPI references `#/components/schemas/HealthResponse`.

## Spec Change Log

## Review Triage Log

| # | Finding (pre-implementation spec review) | Verdict | Action |
|---|---|---|---|
| 1 | No `src/app/__init__.py`, so the build fails before the test runs | high | create it in the pyproject task; expected red is now named |
| 2 | Re-exports fail `mypy --strict` | high | `__all__` required in package `__init__` |
| 3 | Starlette 1.10 `TestClient` warns that `httpx` is deprecated in favour of `httpx2` | medium | dev dependency is `httpx2`; to be confirmed by a warning-free test run |
| 4 | pyproject left open: name, version, `uv init`, ruff rules | medium | all fixed in the task |
| 5 | Package `__init__.py` files not listed | medium | listed per directory |
| 6 | `pydantic` used but not declared | low | declared |
| 7 | Schemas and endpoints follow different layouts | low | schemas mirror the endpoints pattern |
| 8 | Design note claimed uv_build may ship an empty package | low | corrected |
| 9 | Settings fields without defaults trip mypy without the pydantic plugin | low | noted in Design Notes |
| R1 | HEAD /health returns 405 (edge-case) | low | rejected: every planned probe (deploy gate, compose healthcheck, Prometheus) uses GET; the fix adds a parameter for an unseen caller |
| R2 | `get_settings()` cache is filled at import, so overrides are ignored (edge-case, blind) | low | rejected: no test overrides settings yet; the first one fails loudly and is fixed with `get_settings.cache_clear()` |
| R3 | A generic `APP_NAME` env var replaces the title (edge-case) | low | rejected: cosmetic, and the fix adds an env prefix nobody asked for |
| R4 | OpenAPI contract (`HealthResponse` ref, literal, title) is not tested (verification-gap) | medium | patch: add `test_openapi_lists_health_schema` |
| R5 | The "no warnings" criterion is not enforced (verification-gap, blind) | medium | patch: `filterwarnings = ["error"]` in pytest config |
| R6 | Module-level `app` is not exercised by any test (verification-gap) | low | defer: the DevOps phase healthcheck runs `app.main:app` end to end |
| R7 | The review diff left out `uv.lock` and the spec (blind) | false | `uv.lock` is generated and left out of the review on purpose; the spec is the claims file, not code |
| R8 | ADR 11 import rules: `config`, core-to-core imports and the `application_services` callers are unspecified (blind) | medium | defer: the fix edits the ADR and agent rules |
| R9 | `backend.md` Data section drops `naming_convention` and background sessions from ADR 11 (blind) | medium | defer: the fix edits agent rules |
| R10 | `expire_on_commit` is not pinned, so expired ORM attributes may reload after commit (blind) | maybe-false | defer: no database code yet; settle when the session dependency is written |
| R11 | CLAUDE.md still names `app/`, `tests/` and `migrations/` (blind) | false | CLAUDE.md already says "Loaded only for files under `backend/`" |
| R12 | `TestClient` used without `with`, so lifespan is skipped and the first test sets the template (blind) | low | patch: use `with TestClient(create_app()) as client` (direct correction) |
| R1 | Edge: `HEAD /health` returns 405 | low, rejected | no planned probe uses HEAD; the deploy gate and the healthcheck use GET |
| R2 | Edge/Blind: `create_app()` at import fills the `get_settings` cache, so overrides need `cache_clear()` | medium | defer: real once settings vary per test; resolve when the database settings land |
| R3 | Edge: a generic `APP_NAME` env var would override the title | low, rejected | unlikely in containers with an explicit env; adding a prefix is a new convention |
| R4 | VerifGap: OpenAPI contract for `/health` untested | medium | patch: `test_openapi_lists_health_schema` |
| R5 | VerifGap/Blind: "no warnings" not enforced by plain `uv run pytest` | medium | patch: `filterwarnings = ["error"]` |
| R6 | VerifGap: module-level `app` used by uvicorn not covered by tests | low | defer: the container healthcheck in the DevOps phase exercises `app.main:app` |
| R7 | Blind: `uv.lock` and spec missing from the review diff | false | `uv.lock` was excluded from the review diff on purpose and checked with `uv lock --check`; the spec is the claims file by design |
| R8 | Blind: import rules ambiguous (`config` not listed, can core features import each other, who may call `application_services`) | medium | defer: fix edits ADR 11 and `backend.md` (agent-context files) |
| R9 | Blind: `backend.md` lacks the ADR's `naming_convention` and background-session rules | medium | defer: agent-context file |
| R10 | Blind: no `expire_on_commit=False` rule; ORM serialization after commit raises `MissingGreenlet` | maybe-false, would be medium | defer: no database code yet; settle in the database spec |
| R11 | Blind: `CLAUDE.md` still says rules load for `app/`, `tests/`, `migrations/` | false | `CLAUDE.md` already says "Loaded only for files under `backend/`" |
| R12 | Blind: `TestClient` used without `with`, so lifespan never runs | low | patch: direct correction, sets the template for later tests |

## Design Notes

- **uv_build module name.** By default, uv_build expects the module to be named after the project (`src/backend/`). Without `module-name = "app"` the build fails.
- **Settings and mypy.** A `Settings` field without a default makes `Settings()` fail `mypy --strict` (call-arg) unless the pydantic mypy plugin is enabled. Enable the plugin when the first required setting, such as the database URL, arrives.
- **Known follow-up.** `/health` does not touch the database. When PostgreSQL lands, `/health` must check it, because it is the deploy gate in architecture AD-9.

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all tests pass, no warnings
- `cd backend && uv run ruff check . && uv run ruff format --check .` -- expected: no issues
- `cd backend && uv run mypy src tests` -- expected: no issues
- `cd backend && uv run uvicorn app.main:app --port 8000` then `curl -i localhost:8000/health` -- expected: `200` and `{"status":"ok"}`

---
paths:
  - "backend/**"
---

# Backend

## Structure
- Layout and import rules are in `docs/adr/0011-feature-sliced-backend-layout.md`. The package is
  `app` under `backend/src/`; never import it as `src.app`.
- Inside a feature: `endpoints → services → repositories → models`. Endpoints never import
  `repositories` or `models`; services may import `models`. Only
  `endpoints` import `schemas`; services take plain arguments or a command dataclass and return
  models or dataclasses.
- `services`, `repositories` and `models` never import `fastapi` or `starlette`. Services raise
  domain exceptions; the API layer turns them into HTTP responses.
- Regular features never import each other. Core features may be imported by anyone and import
  each other one way only. `app.config` and `common` are importable everywhere.
- Cross-feature work lives in `application_services`, called only by endpoints of regular features
  and `infrastructure.background_tasks`, never by core features.
- `common` imports no features. Import contracts live in `backend/pyproject.toml`; wildcards
  cover new features. When `app.common`, `app.features.application_services` or
  `app.infrastructure.background_tasks` is created, drop `.**` for it there. `uv run lint-imports`
  must pass.
- Create a directory together with its first file, never empty in advance.

## Data
- Models use `DeclarativeBase` and `Mapped[...]`. The base `MetaData` has a `naming_convention`.
  Every model module is imported by the model registry that Alembic's `env.py` loads.
- Repositories only `flush()`, never `commit()`. The request session dependency commits, and it is
  always used with `scope="function"` so the commit happens before the response is sent.
  Background tasks open their own session and transaction.
- SQLAlchemy stores the enum member name, not its value. PostgreSQL enum labels and
  `server_default` values must be the uppercase names; lowercase values are for API JSON only.
- A second foreign key to the same table needs an explicit `foreign_keys=` on both sides of every
  relationship between those two tables.
- Existing migrations are never edited. A schema fix is always a new revision.
- Write migration files but never apply them with `alembic upgrade` unless asked. Running tests is fine.

## Configuration
- TTLs, timeouts and limits that may change live in settings with defaults, never as scattered
  module constants. Protocol codes, such as WebSocket close codes, stay constants.

## Errors
- HTTP error translation belongs to the API layer. Background workers catch exceptions, roll back
  and log; they never raise HTTP exceptions.

## LLM features
- AI orchestration lives in its own module. Domain services never import it.
- Before designing an AI tool, ask what users will actually ask. Do not infer scope from the data shape.
- Clean extraction output comes from the schema and field descriptions given to the model, not from
  speculative server-side normalization. Keep the response model lenient; review is the safety net.

## API checks
- Collections and end-to-end checks cover happy paths and data-state errors only, not trivial
  401 or missing-field cases.

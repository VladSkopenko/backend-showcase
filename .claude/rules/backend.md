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
- Each feature folder answers one question: `models/` are database tables, `schemas/` are HTTP
  input and output (Pydantic, endpoints only), `dto/` are service input and output (dataclasses),
  `enums/` are shared enumerations, `templates/` are files a service renders (e.g. emails),
  `services/` hold only classes with behaviour plus `exceptions.py`. Domain error codes and messages live in `services/exceptions.py`, never in
  endpoints. import-linter keeps `dto` and `enums` free of HTTP and `dto` free of `schemas`.
- Route handlers only map the request schema to a service call and the result to a response
  schema; no helper functions in route modules. FastAPI wiring lives next to them:
  `endpoints/dependencies.py` (providers and `Annotated` aliases) and `endpoints/errors.py`
  (domain error to HTTP status). Any decision or side effect, including email sending and
  environment-dependent behaviour, belongs to a service.
- Object-oriented style, as in `app/infrastructure/email`: repositories are classes holding the
  session, services are classes with constructor-injected dependencies, one class per file,
  keyword-only arguments on public methods. A service builds its own repositories from the
  injected session, because endpoints may not import repositories; every other collaborator is
  injected. Services receive only the settings values they use, not the whole `Settings`. Plain functions only for generic stateless helpers in
  `app/common`.
- Code explains itself through names and structure. No comments or docstrings that restate the
  code; a comment is allowed only for a reason the code cannot show, such as a library gotcha.
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
- Enum members use the same uppercase string for name and value (`VERIFIED = "VERIFIED"`), so the
  database label, the API JSON and the code always read the same. PostgreSQL enum labels and
  `server_default` values are these uppercase strings.
- A second foreign key to the same table needs an explicit `foreign_keys=` on both sides of every
  relationship between those two tables.
- Merged or deployed migrations are never edited; a schema fix to them is always a new revision. A
  migration that exists only in the current branch may be changed until it is merged.
- Write migration files but never apply them with `alembic upgrade` unless asked. Running tests is fine.

## Configuration
- Any value that may plausibly need changing (TTLs, timeouts, limits, the JWT algorithm, cookie
  paths) lives in settings with a default, so changing it needs no code edit. Protocol codes, such as
  WebSocket close codes, stay constants.
- A constant that belongs to one class is a class attribute (`SessionCookies.ACCESS_NAME`). A
  module-level constant only when no class owns it.

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

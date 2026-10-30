---
paths:
  - "backend/**"
---

# Backend

## Structure
- Layout and import rules are in `docs/adr/0011-feature-sliced-backend-layout.md`. The package is
  `app` under `backend/src/`; never import it as `src.app`.
- Inside a feature: `endpoints → services → repositories → models`. Features import only `core`
  features and `common`, never each other. Cross-feature work lives in `application_services`.
- Create a directory together with its first file, never empty in advance.

## Data
- Models use `DeclarativeBase` and `Mapped[...]`. Every model module is imported by the model
  registry that Alembic's `env.py` loads.
- Repositories only `flush()`, never `commit()`. The request session dependency commits, and it is
  always used with `scope="function"` so the commit happens before the response is sent.
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

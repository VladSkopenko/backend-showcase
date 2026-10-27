---
paths:
  - "app/**"
  - "tests/**"
  - "migrations/**"
---

# Backend

## Data
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

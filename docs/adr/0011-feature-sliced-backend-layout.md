# 11. Feature-sliced backend layout

Date: 2026-10-28

## Status

Accepted. Amended 2026-11-01: the import rules were completed and are now enforced by
import-linter in CI.

## Context

The backend will grow from a health check to bookings, orders, payments, invoices, reviews and domain
events. Layering only by technical type (`models/`, `services/`, `routers/` at the top) scatters each
feature across the tree. Slicing only by feature, with no rules between slices, lets features import
each other until nothing can change in isolation. The transactional outbox (README, Phase 7) also needs
each domain write and its event to land in one transaction, so the place where transactions commit has
to be fixed before any data code exists.

## Decision

Source lives in `backend/src/app/` (src layout, the importable package is `app`):

```
app/
├── main.py              # FastAPI app, lifespan, middleware, routers
├── config/settings.py   # pydantic Settings behind a cached get_settings()
├── common/              # shared code with no business logic
├── features/
│   ├── core/<feature>/  # base domains others build on: users, auth, health
│   ├── <feature>/       # endpoints/, schemas/, services/, repositories/, models/
│   └── application_services/  # orchestration across features
└── infrastructure/      # background tasks, WebSocket
```

Dependency rules:

- Inside a feature, calls go one way: `endpoints → services → repositories → models`. Endpoints
  never import `repositories` or `models`; they reach data only through services. Services may
  import `models` directly, because they return them.
- Only `endpoints` import `schemas`. An endpoint parses the request schema, calls the service with
  plain arguments or a small command dataclass, and builds the response schema from what the
  service returns (`Schema.model_validate(obj)` with `from_attributes`).
- Services know nothing about HTTP. `services`, `repositories`, `models`, `application_services`
  and background tasks never import `fastapi` or `starlette`. Services raise domain exceptions, and the API layer translates them into HTTP
  responses, so a service can run from an endpoint, a background task, a cron job or a script.
- Everything may import `app.config` and `common`.
- Regular features never import each other. Any feature may import `core` features. Core features
  may import each other in one direction only, never in a cycle.
- `common` imports no features at all, core included. Core never imports regular features.
- Work that spans features lives only in `application_services`. Only endpoints of regular
  features and `infrastructure.background_tasks` call it; core features never do.
- Core features importing each other in one direction only is a convention; no contract checks it.
- These rules are checked by import-linter contracts in `backend/pyproject.toml`, run in CI.

Data rules, binding from the first model on:

- Models use SQLAlchemy 2.0 `DeclarativeBase` with `Mapped[...]` columns.
- The base `MetaData` carries a `naming_convention`, so constraints get stable names in migrations.
- One registry module imports every feature's models. Alembic's `env.py` imports that module, so
  autogenerate always sees every table.
- Repositories only `flush()`. One transaction per request commits in the session dependency. The
  dependency runs with `scope="function"`, so the commit finishes before the response is sent.
  Background tasks open their own session and transaction.

Directories are created with their first file. Nothing exists ahead of time to show the structure.

## Alternatives considered

- **Layers by technical type.** Familiar, but every feature change touches four directories, and
  nothing stops cross-feature imports.
- **Full hexagonal architecture with ports and adapters per feature.** Clean boundaries, but too
  much ceremony for a single API with one database.

## Consequences

- Each feature can be read, tested and changed in one place. A cross-feature flow is easy to find,
  because it can only live in `application_services`.
- A commit that fails reaches the client as an error, not as a 200 with lost data.
- The import rules are enforced by import-linter in CI, so a violation fails the pull request
  instead of waiting for a reviewer to notice it.
- New features are picked up by the contracts' wildcards automatically. The one manual step: when
  `app.common`, `app.features.application_services` or `app.infrastructure.background_tasks` is
  created, drop the `.**` suffix in the contracts so the package's own `__init__` is checked too.

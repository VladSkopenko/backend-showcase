# 11. Feature-sliced backend layout

Date: 2026-10-28

## Status

Accepted

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

- Inside a feature, calls go one way: `endpoints → services → repositories → models`.
- A feature may import `core` features and `common`. Features never import each other.
- Work that spans features lives only in `application_services`.
- `common` and `core` never import non-core features.

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
- The import rules are a convention for now. An import linter can enforce them later if they start
  slipping.

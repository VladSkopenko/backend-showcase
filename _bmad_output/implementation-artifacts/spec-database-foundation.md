---
title: 'Database foundation: PostgreSQL, SQLAlchemy, Alembic and the User model'
type: 'feature'
created: '2026-11-04'
status: 'done'
baseline_commit: '6de4649e879184a799d545ff0659d502144e2018'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/docs/adr/0005-migration-rollback-with-alembic.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The backend has no database, so Google OAuth (the next PR) has nowhere to store users. Dev runs only the API container.

**Approach:** Add async SQLAlchemy, Alembic and a `users` table, run PostgreSQL 18 in every `app-<env>` stack, pass its password from the GitHub Environment over SSH stdin, and migrate to head on every deploy before the new API starts.

## Boundaries & Constraints

**Always:**
- `User`: `id` UUID (server default `gen_random_uuid()`), `name` (required, ≤100), `email` (required, unique, ≤320), `password_hash` (optional: OAuth users have none), `email_verified_at` (optional, timezone-aware: set by the email verification flow; Google sign-in counts as verified). No phone field: the Figma registration flow has none and SMS is not affordable, `created_at` (server default `now()`), `updated_at` (server default `now()`, `onupdate=func.now()`), both timezone-aware.
- Decision: settings are split by domain. One root `Settings` behind the cached `get_settings()` holds `app: AppSettings` (`APP_` prefix, `name`) and `database: DatabaseSettings` (`DATABASE_` prefix: `host`, `port`, `user`, `password: SecretStr`, `name`, and a `url` property built with `sqlalchemy.URL.create`). Defaults match the local database. Later domains (e.g. `GOOGLE_`) add their own class.
- ADR 11 and `.claude/rules/backend.md` data rules: `DeclarativeBase` with `naming_convention`, a model registry imported by `env.py`, repositories never commit, the session dependency commits or rolls back, `expire_on_commit=False`.
- Migration has a working `downgrade()`; CI runs `upgrade head`, `downgrade base`, `upgrade head` (AD-10).
- Decision: migrations target `head`, never `heads`; a second head fails CI and is resolved with `alembic merge`.
- Decision: database tests always hit a real PostgreSQL. Locally it comes from `backend/compose.yml` (`127.0.0.1:5433`, because 5432 is often taken by other local projects), started once with `docker compose up -d`; the test session migrates it to head itself.
- Postgres stays on the project's private network, never on `edge` (AD-13); data bind-mounted under `/srv/data/<env>/postgres` (AD-11); `mem_limit` set and `shared_buffers=128MB` (AD-12).
- The secret never appears in argv, logs or the repo.
- Decision: Vlad asked on 2026-11-04 that the infrastructure files in this PR (compose files, Dockerfile, workflows, `deploy.sh`) are written by the agent.

**Never:** user endpoints, services or repositories; Redis; auth code; migration rollback and previous-digest restore on a failed health gate (AD-9 rollback is deferred); running `alembic upgrade` by hand against a local database.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Commit | dependency body adds a `User` and returns | row visible after the dependency exits | N/A |
| Rollback | dependency body raises | no row, exception re-raised | session rolled back |
| Duplicate email | second `User` with an existing email | flush fails | `IntegrityError` on `uq_users_email` |
| First deploy | empty `/srv/data/dev/postgres` | Postgres initialises, migration creates `users`, API healthy | failed migration fails the deploy; running API untouched |
| Redeploy | schema at head | `alembic upgrade head` is a no-op, Postgres not restarted | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/config/settings.py` -- today a flat `Settings` with `app_name`; `main.py` reads `get_settings().app_name` and `tests/test_health.py` asserts the title `backend-showcase`.
- `backend/pyproject.toml` -- import-linter contract "Common imports no features" lists `app.common.**`; switch to `app.common` once the package exists (ADR 11). `filterwarnings = ["error"]`.
- `backend/Dockerfile` -- runtime stage copies only `.venv`, no `WORKDIR`; migrations must ship in the image because deploy runs them with the new image. asyncpg 0.32 ships cp314 manylinux aarch64 wheels.
- `backend/tests/test_health.py` -- sync `TestClient` style. Async tests use the `anyio` pytest plugin (installed with Starlette); no new test dependency.
- `deploy/app/compose.yml`, `deploy/app/deploy.sh` -- `--env-file` feeds interpolation only; the container gets nothing unless declared under `environment`.
- `.github/workflows/delivery.yml` `deploy-dev` -- pipes `< /dev/null` into ssh today.
- `.github/workflows/ci.yml` -- backend job on the runner host, no services.

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- `uv add "sqlalchemy[asyncio]" asyncpg alembic`; contract source `app.common`.
- [x] `backend/compose.yml` -- local `postgres:18`, user/password/database `app`, `127.0.0.1:5433:5432`, named volume.
- [x] `backend/tests/conftest.py` -- sync session-scoped fixture runs `alembic.command.upgrade(Config("alembic.ini"), "head")` (sync because the async `env.py` calls `asyncio.run`); a test engine with `NullPool`, disposed in teardown; a connection fixture in an outer transaction rolled back after each test; tests drive `get_session` by patching its sessionmaker to `AsyncSession(bind=connection, join_transaction_mode="create_savepoint")`. Keep anyio fixtures function-scoped or override `anyio_backend` at the same scope.
- [x] `backend/tests/test_database.py` -- matrix rows Commit, Rollback, Duplicate email; the migrated `users` table has the columns and nullability above.
- [x] `backend/tests/test_settings.py` -- `DATABASE_*` and `APP_*` env vars land in their blocks; `database.url` escapes a password with `@` and `/`; the password is hidden in `repr`.
- [x] `backend/src/app/config/settings.py` -- domain classes as decided; `main.py` uses `get_settings().app.name`.
- [x] `backend/src/app/common/__init__.py`, `common/database.py` -- `Base` with `naming_convention`; cached engine and `async_sessionmaker(expire_on_commit=False)` built from `database.url`; `get_session` async generator: commit on success, rollback on error; used later as `Depends(get_session, scope="function")`.
- [x] `backend/src/app/features/core/users/__init__.py`, `models/__init__.py`, `models/user.py` -- `User`.
- [x] `backend/src/app/model_registry.py` -- imports every feature's models (outside `common`).
- [x] `backend/alembic.ini`, `backend/migrations/env.py`, `script.py.mako`, `versions/0001_create_users.py` -- async env from `get_settings().database.url` and the registry's `Base.metadata`; template output must pass ruff (no `typing.Union`/`Sequence` imports).
- [x] `backend/tests/test_database.py`, `backend/src/app/features/core/users/models/user.py`, `backend/migrations/versions/0002_add_verification_timestamps.py` -- add `email_verified_at` (nullable `DateTime(timezone=True)`) in a new revision; 0001 is never edited (backend.md); extend the column test.
- [x] `backend/Dockerfile` -- runtime `WORKDIR /app`, copy `alembic.ini` and `migrations/`.
- [x] `.github/workflows/ci.yml` -- `postgres:18` service with `ports: ["5433:5432"]`, `POSTGRES_USER/PASSWORD/DB=app`, `--health-cmd "pg_isready -h 127.0.0.1"` options; migration round-trip step before tests.
- [x] `deploy/app/compose.yml` -- `postgres:18`: `POSTGRES_USER/DB: app`, `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}`, healthcheck `pg_isready -h 127.0.0.1 -U app -d app`, `/srv/data/${APP_ENV}/postgres:/var/lib/postgresql`, `mem_limit: 512m`, `command: postgres -c shared_buffers=128MB`. `api`: `DATABASE_HOST: postgres`, `DATABASE_PORT: "5432"`, `DATABASE_PASSWORD: ${POSTGRES_PASSWORD:?}`, `depends_on` postgres `service_healthy`.
- [x] `deploy/app/deploy.sh` -- `up --detach --wait postgres`, `run --rm --no-deps api alembic upgrade head`, `up --detach --wait api`.
- [x] `.github/workflows/delivery.yml` -- `deploy-dev`: `env: POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}`, `printf 'POSTGRES_PASSWORD=%s\n' "$POSTGRES_PASSWORD" | ssh ...` instead of `< /dev/null`.
- [x] `CLAUDE.md` -- Commands: `docker compose up -d` in `backend/` starts the local database.
- [x] `_bmad_output/implementation-artifacts/deferred-work.md` -- add the AD-9 rollback entry.

**Acceptance Criteria:**
- Given a merge to `main` with the `dev` secret `POSTGRES_PASSWORD` set, when Deploy dev runs, then `app-dev` has healthy `postgres` and `api`, and the `users` table exists.
- Given CI on a PR, then lint, mypy, import-linter, the migration round-trip and tests pass.

## Design Notes

- PostgreSQL 18 images declare the volume at `/var/lib/postgresql` (PGDATA `/var/lib/postgresql/18/docker`); the ≤17 mount `/var/lib/postgresql/data` loses data on re-create.
- During first init the temporary server listens only on the unix socket, so the healthcheck must probe TCP (`-h 127.0.0.1`) or migrations race the init.
- `POSTGRES_PASSWORD` only applies to an empty data directory; changing the secret later breaks the API until the role password is changed in the database.

## Verification

**Commands:**
- `cd backend && docker compose up -d && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.
- `actionlint .github/workflows/*.yml` and `docker compose -f deploy/app/compose.yml config --quiet` (with `IMAGE`, `APP_ENV`, `POSTGRES_PASSWORD` set) -- clean.

## Implementation Notes

## Spec Change Log

- 2026-11-04, during review: Vlad added `email_verified_at` and `phone_verified_at` to the User model (frozen block amended at his request). Delivered as migration 0002 because 0001 was already applied to local databases. KEEP: everything else from the first pass, including the review patches.
- 2026-11-04: Vlad chose email-only verification (phone stays optional and unverified), so `phone_verified_at` was removed from the unmerged 0002, and `phone` from the unmerged 0001 (absent from the Figma registration flow). Convention from Vlad: migrations not yet merged or deployed may be edited; applied ones never.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | verification-gap, blind | No check that `User` metadata matches migration 0001 | medium | CI round-trip runs only migration files; dropping `unique=True` passes every test. Patch: `alembic check` after the final `upgrade head` in CI. |
| 2 | verification-gap | Built image never runs Alembic before push | low | Missing `COPY migrations` would surface only at deploy, where the old API keeps serving. Rejected: undemonstrated regression, fix adds a pipeline step. |
| 3 | verification-gap | `onupdate=func.now()` untested | low | No update path exists yet, and `now()` is constant inside one test transaction. Rejected: belongs with the first update path (OAuth PR). |
| 4 | blind, edge-case | Unquoted `.env` value mangles a password with `$`, ` #` or newline | low | Postgres and API get the same value; only manual use differs. Patch: comment that the secret must be alphanumeric. |
| 5 | blind | `.env` points at the new digest before migrations succeed | low | Containers restart from their own config, not `.env`; only a manual `compose up` (forbidden by AD-2) is affected. Rejected; covered by the AD-9 rollback entry. |
| 6 | blind | mypy does not check `migrations/` | low | `mypy src tests` in CI and CLAUDE.md. Defer: the fix edits CLAUDE.md. |
| 7 | blind, edge-case | Cached engine has no `pool_pre_ping` | medium | After a Postgres restart the first request per pooled connection fails. Patch: `pool_pre_ping=True`. |
| 8 | blind, edge-case | Engine not disposed on shutdown; ResourceWarnings in tests | false | Tests patch `get_sessionmaker` and use their own NullPool engine; the app engine is never created in tests, and process exit closes sockets. |
| 9 | blind, edge-case | `Config("alembic.ini")` depends on cwd | low | `pytest` from the repo root fails in setup. Patch: path from `__file__`. |
| 10 | blind, edge-case | Stray `backend/env.example` | false | Not part of this change: Vlad's own untracked file, left for his decision. |
| 11 | blind | Revision ID and file naming convention undocumented | low | Next autogenerate yields a hex id and unsorted files. Defer: convention choice. |
| 12 | blind | Local compose has no healthcheck | low | `up -d` then `pytest` on a fresh volume can race init. Patch: `pg_isready -h 127.0.0.1` healthcheck; CLAUDE.md `--wait` deferred with #6. |
| 13 | blind | No password rotation procedure | medium | Changing the secret breaks the API until `ALTER ROLE`. Defer: runbook. |
| 14 | blind | `scope="function"` commit-before-response untested | low | No route uses `get_session` yet. Rejected: test with the first route (OAuth PR). |
| 15 | edge-case | Migration can hang on a lock | maybe-false | Would need a lock holder; the old API does not touch the database yet. Rejected as low until a DB-using API exists. |
| 16 | edge-case | Healthcheck fails if initdb exceeds 50 s | low | initdb on an empty dir takes seconds. Rejected: undemonstrated. |
| 17 | edge-case | Email uniqueness is case-sensitive | medium | `Ada@x.com` and `ada@x.com` both insert. Defer to the OAuth PR, which writes users and must normalise email. |
| 18 | edge-case | `env.py` `fileConfig` reconfigures logging inside pytest | low | No caplog tests exist. Rejected. |
| 19 | edge-case | Template imports unused in manual revisions | low | Autogenerate, the normal path, uses them. Rejected. |

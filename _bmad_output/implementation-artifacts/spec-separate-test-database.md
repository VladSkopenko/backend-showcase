---
title: 'Run the test suite on a separate database'
type: 'chore'
created: '2026-11-05'
status: 'done'
baseline_commit: '85faff7f020214687a8ec4efe77dc1562b82046d'
route: 'dispatch'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The test session migrates whatever database the settings point at, which is the developer's working database `app`. An unmerged migration edited in place therefore needs a manual downgrade of `app`, and every test run writes migrations into it.

**Approach:** Decision (Vlad, 2026-11-05): tests use their own database `app_test` on the same PostgreSQL server. The test session drops and recreates it, then migrates it to head from scratch, so `app` is never touched by tests.

## Boundaries & Constraints

**Always:**
- `tests/conftest.py` forces `DATABASE_NAME=app_test` at module top, next to `TOKEN_SECRET_KEY`, before any test module or alembic builds the cached settings. Other `DATABASE_` variables (host, port, user, password) still pass through, so a run can target another server.
- At session start, before `alembic upgrade head`: connect to the maintenance database `postgres` with `AUTOCOMMIT` (both statements refuse to run in a transaction block), then `DROP DATABASE IF EXISTS app_test WITH (FORCE)` and `CREATE DATABASE app_test`.
- One test run per PostgreSQL server at a time: a second run drops `app_test` under the first. pytest-xdist is not supported. Stated in CLAUDE.md.
- Before the drop, the session checks that `get_settings().database.name` equals the test database name and stops otherwise, so a settings cache filled before the override (e.g. `app.main` imported above the env block; it builds settings at import) can never migrate `app`. The name lives in one place in conftest and feeds the env value, the check and both statements.
- Works unchanged in CI: the `postgres:18` service user is a superuser and the server has the `postgres` database. The CI migration round-trip step keeps running against `app`.
- `backend/compose.yml` comment and the CLAUDE.md Commands line say tests use `app_test`, recreated per run, never touch `app`, and run one at a time.

**Never:** a second PostgreSQL container, an init script in compose, changes to application settings or `migrations/env.py`, data in `app` touched by tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First run | no `app_test` | created, migrated to head, suite passes | N/A |
| Repeat run | `app_test` left by the previous run | dropped and recreated; suite passes | N/A |
| Edited unmerged migration | `app_test` built from the old revision | rebuilt from the new revision; no manual downgrade | N/A |
| Working database | `app` at any revision with data | revision and row counts of `users`, `verification_codes`, `refresh_tokens` unchanged after `uv run pytest` | N/A |
| Settings cached too early | `get_settings().database.name` is not `app_test` at session start | session stops before any DDL | N/A |
| Stale connection | a client left connected to `app_test` | `FORCE` terminates it; drop succeeds | N/A |

</frozen-after-approval>

## Code Map

- `backend/tests/conftest.py` -- module-top env handling (`TOKEN_SECRET_KEY`), `env_file` disabled for every settings class, `isolated_settings_env` keeps `DATABASE_` variables, sync session fixture `migrated_database` runs `command.upgrade(..., "head")` (sync because `env.py` calls `asyncio.run`).
- `backend/src/app/config/settings.py` -- `DatabaseSettings.url` built with `URL.create`; `URL.set(database="postgres")` gives the maintenance URL.
- `backend/migrations/env.py` -- builds its engine from `get_settings().database.url`, so the forced name reaches alembic.
- `backend/compose.yml`, `CLAUDE.md` (Commands: "Local database" line) -- wording only.
- `.github/workflows/ci.yml` -- unchanged; the round-trip step uses `app`, pytest then uses `app_test`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/conftest.py` -- force `DATABASE_NAME` from one name constant; check the cached settings use it; recreate `app_test` through the maintenance database with `AUTOCOMMIT` inside `migrated_database` (one `asyncio.run`, engine disposed: `filterwarnings = ["error"]` fails on a leaked connection), then upgrade to head; reword the `isolated_settings_env` comment (DATABASE_ variables now select the server, not the database).
- [x] `backend/compose.yml` -- comment: tests recreate `app_test` per run.
- [x] `CLAUDE.md` -- Commands: "tests recreate their own `app_test` database and never touch `app`; run one at a time".

**Acceptance Criteria:**
- Given `app` at revision R with rows, when `uv run pytest` runs twice, then both runs pass and `app` still reports revision R with the same counts in `users`, `verification_codes` and `refresh_tokens` (the repeat run also covers the edited-migration row).
- Given a `psql` session left open on `app_test`, when `uv run pytest` runs, then it passes.
- Given CI, then the migration round-trip and the test suite pass.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest && uv run pytest` -- all pass.
- Read-only before and after: `SELECT version_num FROM alembic_version` and counts of `users`, `verification_codes`, `refresh_tokens` on `app` -- unchanged; `SELECT datname FROM pg_database` lists `app_test`.

## Implementation Notes

- Verified 2026-11-05: `app` before the change at revision `0003` with 3/3/3 rows in `users`/`verification_codes`/`refresh_tokens`; after two consecutive `uv run pytest` runs (93 passed each) still `0003` and 3/3/3; `pg_database` lists `app_test`.
- Stale connection: a client holding `pg_sleep(120)` on `app_test` was terminated by `FORCE` and the run passed. Early cache: a scratchpad plugin calling `get_settings()` before conftest made the session exit with code 2 before any DDL.
- Review: CLAUDE.md gains a "Migrate the working database" command, because tests no longer bring `app` to head.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | Two concurrent pytest runs drop each other's database | medium | `DROP ... WITH (FORCE)` terminates the other run; review subagents run pytest in parallel. Patched: one run per server, documented. |
| 2 | spec review | A settings cache filled before the override silently migrates `app` | medium | `app/main.py` builds settings at import. Patched: name check before DDL, one constant. |
| 3 | spec review | Acceptance counts only `users`; stale-connection row unchecked | low | Patched AC and Verification. |
| 4 | spec review | conftest comment on DATABASE_ variables becomes wrong | low | Patched task. |
| 5 | verification-gap | The early-cache guard has no automated test | medium | Needs a `pytester` subprocess run; checked manually. Defer. |
| 6 | blind | Nothing migrates `app` any more, and CLAUDE.md has no migrate command | medium | Tests used to bring `app` to head. Patch: CLAUDE.md "Migrate the working database". |
| 7 | blind, edge | One-run-at-a-time is documentation only; no advisory lock | low | Spec decision (row 1): documented, no extra mechanism. Rejected. |
| 8 | blind | The real source of parallel runs is review subagents, not xdist; no rule tells agents not to run pytest | medium | Review prompts this session needed an explicit "do not run pytest". Defer: the fix edits `.claude/rules/workflow.md`. |
| 9 | blind, edge | No guard against recreating `app_test` on a non-local server | low | Pointing at another server is intended; only `app_test` is dropped there. Rejected. |
| 10 | edge | Missing CREATEDB or `postgres` database gives a raw asyncpg error | low | Local and CI users are superusers with `postgres` present. Rejected. |
| 11 | blind | The "two runs break each other" comment sits above the env block | low | Patch: moved into `recreate_test_database`. |
| 12 | blind | No ADR for the test database contract | low | workflow.md rule 5. Defer with the ADR batch. |
| 13 | blind | Spec untracked and Implementation Notes empty | low | Patch: notes record the verification. |

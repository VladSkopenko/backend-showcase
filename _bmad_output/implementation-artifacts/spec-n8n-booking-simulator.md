---
title: 'Booking simulator: n8n bots that book tables on dev'
type: 'feature'
created: '2026-11-11'
status: 'done'
baseline_commit: '6bd9bf7cde0527e6667ac6b01b9edbbf397cb5be'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0013-table-booking-slots-and-double-booking.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-book-a-table.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Dev shows an empty booking grid, so nobody sees the booking flow move. The roadmap plans n8n as a visitor simulator that books random tables through the REST API.

**Approach:** A local n8n (`n8n/compose.yml`) runs the workflow `n8n/workflows/booking-simulator.json`, already written and tried by Vlad against the local API. This story adds the bot accounts on dev through a data migration that runs only when `APP_ENVIRONMENT` is `dev`, a short runbook for the local n8n, and an ADR. Deploying n8n to the platform stack is a later story.

## Boundaries & Constraints

**Always:**
- Decisions (Vlad, 2026-11-11): the simulator runs only on dev, never on staging or prod, where it would take real guests' tables. Bots come from a migration instead of registration, so no mailbox is needed. The workflow books only where at least 4 fitting tables are free at one location and start time.
- Migration `0011` revises `0010`. When `get_settings().app.environment == "dev"` it inserts four users: emails `booking-bot-1@example.com` to `booking-bot-4@example.com`, `first_name` `Booking`, `last_name` `Bot 1` to `Bot 4`, `email_verified_at`, `created_at` and `updated_at` all `2026-11-11 12:00 UTC`, and the same `password_hash` for all four: `$argon2id$v=19$m=65536,t=3,p=4$Lf2JoTtceyf2Fd6S/nVkYg$DtRYerfEvFEpwj+u7XZvNnKmV8N8DGK0iDm+br4R0OM`. In any other environment both upgrade and downgrade do nothing.
- Downgrade on dev deletes those four users by email; their bookings go with them through the existing CASCADE.
- A plain insert: if one of the emails already exists on dev, the upgrade fails loudly.
- The plaintext password is never written to the repository; Vlad keeps it and enters it into the n8n credential.
- No comments in backend code, migrations or tests.

**Never:** bots in local, test, staging or prod databases; a password in any file; a registration bypass or a bot flag on users; changes to `n8n/compose.yml` or the workflow JSON; n8n in `deploy/platform/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Local and tests | `APP_ENVIRONMENT` unset or `local` | `alembic upgrade head` adds no users | N/A |
| Dev | `APP_ENVIRONMENT=dev`, upgrade to `0011` | four verified bot users exist; the hash verifies the password | N/A |
| Dev downgrade | `downgrade 0010` | the four bots and their bookings are gone; other users untouched | N/A |
| Email taken on dev | a user with a bot email exists | upgrade aborts | IntegrityError on `uq_users_email` |

</frozen-after-approval>

## Code Map

- `backend/migrations/versions/0008_create_locations.py` -- data-migration style: literals at module level, fixed `datetime(..., tzinfo=UTC)` timestamps.
- `backend/src/app/config/settings.py` -- `get_settings().app.environment`; `migrations/env.py` already builds the settings, and on dev `deploy/app/deploy.sh:29` runs `alembic upgrade head` inside the `api` service, where `deploy/app/compose.yml:32` sets `APP_ENVIRONMENT`.
- `backend/src/app/features/core/users/models/user.py` -- columns of `users`; use a lightweight `sa.table` in the migration, not the model.
- `backend/src/app/features/core/auth/services/password_hasher.py` -- `PasswordHasher.verify`, for the manual hash check.
- `backend/tests/test_locations_data_migration.py` -- data-migration test pattern on the migrated test database.
- `n8n/compose.yml`, `n8n/workflows/booking-simulator.json`, `.gitignore` (`n8n/data/`) -- already written; read for the runbook, do not change.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_booking_bots_migration.py` -- the migrated test database (environment `local`) holds no user with an email starting `booking-bot-`.
- [x] `backend/migrations/versions/0011_add_dev_booking_bots.py` -- the dev-only insert and delete described above.
- [x] `n8n/README.md` -- runbook: start and stop the local n8n; Chrome, not Safari (secure cookie over http); first-run owner account; import with `docker compose -f n8n/compose.yml exec -u node n8n n8n import:workflow --input=/home/node/workflows/booking-simulator.json` and export back with `export:workflow --id=BookingSimul8tor --output=...`, noting that import overwrites the workflow; the `Booking bot password` Custom Auth credential `{"body": {"password": "..."}}`; local bots registered through `/auth/register` and `/auth/verify-email` (local echoes `debug_code`); the API base URL in `Plan the visit`; what each node does and the 4-free-tables rule.
- [x] `docs/adr/0014-booking-simulator-on-dev.md` -- n8n as the visitor simulator on dev only; bots from an environment-gated data migration and why (no mailbox, no registration bypass, nothing in other environments); the password in an n8n credential only; the 4-free-tables rule; deployment to the platform stack left for later.
- [x] `README.md`, `README.uk.md` -- the decisions table stops at ADR 11: add rows for ADR 12, 13 and 14 in the style of the other rows, Ukrainian text in the Ukrainian file.

**Acceptance Criteria:**
- Given a throwaway `postgres:18` and `APP_ENVIRONMENT=dev`, when migrating to head, then four bot users exist with `email_verified_at` set and exactly the `password_hash` from this spec (the orchestrator verified that hash against the password when generating it).
- Given the same database, when downgrading to `0010` and upgrading again, then the bots disappear and come back.
- Given `APP_ENVIRONMENT=local`, when migrating a throwaway database to head, then no bot user exists.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass. Run pytest once, on the local server only: it recreates `app_test`, which other sessions share.
- Throwaway `postgres:18` on a free port, `DATABASE_*` pointed at it: the acceptance criteria above, then `alembic check` -- clean.

## Implementation Notes

- The hash is split into two adjacent string literals: on one line it exceeds the 100-character limit, and `ruff format` joins a parenthesised single literal back into one line.
- The runbook export command adds `--pretty` (listed by `n8n export:workflow --help` in `n8nio/n8n:2.47.4`), so the exported file stays reviewable in git; import leaves the workflow inactive (`--activeState` defaults to `false`), which the runbook says.
- Verified by the implementer: ruff, format check, mypy, lint-imports (9 kept), pytest 378 passed on the local server. Throwaway `postgres:18` on port 5440: `APP_ENVIRONMENT=local` upgrade head, downgrade `0010`, upgrade head leave no users; `APP_ENVIRONMENT=dev` upgrade head adds the four bots with `email_verified_at`, `created_at`, `updated_at` at `2026-11-11 12:00+00` and exactly the spec hash; with a non-bot user and one booking each for bot 1 and that user (inserted with SQL into the throwaway database), downgrade `0010` removes the bots and bot 1's booking and keeps the other user and booking, upgrade brings the bots back; with `booking-bot-3@example.com` pre-inserted, upgrade fails with `IntegrityError` on `uq_users_email` and stays at `0010`; `alembic check` clean. The hash was not verified against the password: the plaintext is not in the repository.
- Review patches by the orchestrator (triage rows 1-7): check nodes after Book and Cancel, `APP_ENVIRONMENT` popped in `conftest.py`, roadmap and ADR 14 wording, the local bot script, the compose comment. Verified: ruff, format, mypy, lint-imports (9 kept), pytest 378 passed.
- Live 2026-11-11: Vlad ran the workflow in the local n8n against the local API many times (15 bookings, 3 cancels by the bots, no bot 4xx); after the re-import with the check nodes a run logged in as `booking-bot-2` and cancelled a booking (200). `n8n execute` cannot run inside the running container (task broker port 5679 is taken).

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | edge, blind | `neverError` hides 401/422/5xx on Book and Cancel | medium | Patched: check nodes let 201/200 and 409 through and fail the run otherwise. |
| 2 | edge | `APP_ENVIRONMENT` from the shell leaks into the session migration of `app_test` | low | `conftest.py` cleared `APP_*` only per test. Patched: popped at import. |
| 3 | blind | Roadmap paragraph confined the kitchen simulator to dev too | low | Patched: dev-only applies to booking bots. |
| 4 | blind | ADR 14 silent on ADR 7 (one n8n for every environment) | low | Patched: Context names the narrowing. |
| 5 | blind | Public hash; password strength not recorded | low | Patched: ADR states a 28-character random password. |
| 6 | blind, edge | Local bot script: unset `BOT_PASSWORD`, string-built JSON, `null` code | low | Patched: `read -rs`, `jq -n --arg`, skip on missing code. |
| 7 | blind | `n8n/compose.yml` comment says the VM already runs n8n | low | Patched: future tense. |
| 8 | verification-gap, edge, blind | Dev branch of `0011` has no automated test | medium | Pre-verified. Defer: needs a second database and a settings override. |
| 9 | blind, edge | Every run logs in and never logs out; `refresh_tokens` grows on dev | low | Real; a logout on every branch reshapes the workflow. Defer. |
| 10 | edge | 4-free rule counts 2- and 4-seaters together | false | Matches Vlad's rule: 4 free fitting tables at one location and start. |
| 11 | blind | Search ignores pagination beyond 50 | false | At most 32 tables seat 1 to 4 guests online. |
| 12 | blind | Hash not verified against the password | false | Verified by the orchestrator with `PasswordHasher.verify` when generated. |
| 13 | edge | Offline `alembic --sql` now needs full settings | low | No offline migration runs in CI or deploy. Rejected. |
| 14 | edge | Wrong password locks the bots out every 5 minutes | low | Operational; the runbook names the credential. Rejected. |
| 15 | edge | Linux: `host.docker.internal`, root-owned `./data` | low | The local file targets Vlad's macOS; the VM gets its own service. Rejected. |
| 16 | edge | Credential id `BookingBotPasswd` differs on other machines | low | The runbook says to select it once. Rejected. |
| 17 | blind | Workflow constants copy server settings | low | Documented per node in the runbook. Rejected. |
| 18 | blind | Spec carries deploy line references | low | Fix edits this spec. Rejected. |

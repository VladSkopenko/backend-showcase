---
title: 'Dev guest bots'
type: 'feature'
created: '2026-11-13'
status: 'done'
baseline_commit: '29d590b29278180b8221ad7967ece166ee695f45'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/patterns.md'
  - '{project-root}/docs/adr/0014-booking-simulator-on-dev.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Four bots cannot produce visitor statistics: the dashboards need distinct people, a few regulars and many occasional guests.

**Approach:** A data migration adds guest bots 5 to 40 on dev, each a verified user with a human first and last name and the shared bot password, so the n8n credential keeps working.

## Boundaries & Constraints

**Always:**
- Migration `0020`, gated on `APP_ENVIRONMENT == "dev"` like `0011`; on any other environment upgrade and downgrade do nothing. Downgrade deletes exactly the added emails.
- Emails `booking-bot-5@example.com` to `booking-bot-40@example.com`; verified; the password hash of `0011` (shared, unchanged); fixed created and verified timestamps.
- 36 distinct first and last name pairs, a mix fitting a Tbilisi restaurant (Georgian and international names), fixed in the migration; no real people.
- Bots 1 to 4 stay as they are. Which bots are regulars is decided by the simulator (story 6), not stored.
- A plain insert: an existing email fails loudly (ADR 14).

**Never:** Bots on local, staging or prod; a bot flag or persona column; changing the password.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Dev upgrade | `APP_ENVIRONMENT=dev`, 0019 | 36 new verified users, distinct names, shared hash | N/A |
| Other env | `local`, `staging`, `prod` | no users added | N/A |
| Dev downgrade | `APP_ENVIRONMENT=dev`, 0020 | the 36 users removed, bots 1 to 4 kept | N/A |
| Taken email | one of the emails exists on dev | migration fails | IntegrityError |

</frozen-after-approval>

## Code Map

- `backend/migrations/versions/0011_add_dev_booking_bots.py` -- the pattern: `sa.table`, `op.bulk_insert`, `PASSWORD_HASH`, environment gate, downgrade by email.
- `backend/migrations/versions/0018_add_staff_bot.py` -- the latest data migration, same shape.
- `backend/migrations/versions/0020_add_dev_guest_bots.py` -- new.
- `backend/tests/test_staff_bot_migration.py` -- how a migration's `upgrade()`/`downgrade()` runs on the test connection under a chosen environment; reuse that approach.
- `backend/tests/test_booking_bots_migration.py` -- asserts no `booking-bot-%` users outside dev; must stay green.
- `docs/adr/0014-booking-simulator-on-dev.md` -- amend: 40 bots, named.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_guest_bots_migration.py` -- new; matrix rows (dev upgrade, other envs, dev downgrade) by running 0020 under each environment on the test connection -- contract.
- [x] `backend/migrations/versions/0020_add_dev_guest_bots.py` -- the migration -- data.
- [x] `docs/adr/0014-booking-simulator-on-dev.md`, `n8n/README.md` (bots section) -- record 40 bots -- docs.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass; CI's round trip and `alembic check` succeed.
- Given a throwaway Postgres migrated with `APP_ENVIRONMENT=dev`, when it reaches head, then 40 booking bots exist and sign-in works for `booking-bot-40@example.com` with the shared password hash.

## Implementation Notes

- 2026-11-13: 0020 adds 36 named bots on dev (22 Georgian, 14 international names). Verified by the parent session: full suite, linters, contracts; the shared bot password (held by Vlad and n8n) verifies against 0020's hash with argon2. The implementer checked the dev upgrade, downgrade, CI round trip and the taken-email failure on a throwaway Postgres. Shared migration test helpers moved to tests/support/migrations.py. The simulator still picks bots 1 to 4 until story 6.
## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route |
|---|---|---|
| Copied test helpers and hash (blind, parent) | low | patch: tests/support/migrations.py |
| Taken-email row and downgrade gate untested (verification-gap, edge-case, blind) | low | patch: tests added |
| Fixed timestamps unchecked (blind) | low | patch |
| n8n README contradicts itself on bots 1-4 vs 40; local bots (blind) | low | patch |
| ADR 14 consequences, cascade note, name wording (blind) | low | patch |
| Downgrade gate deletes real users outside dev if broken (verification-gap) | low | covered by the new gate test |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

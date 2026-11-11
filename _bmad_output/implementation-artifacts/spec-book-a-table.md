---
title: 'Book a table: search, create, list and cancel bookings'
type: 'feature'
created: '2026-11-11'
status: 'done'
baseline_commit: '35c17f33d97a59b373b56a2b60ec1e7670d803c1'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/docs/adr/0012-unified-error-response.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-locations.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Figma "Book a Table" flow (search form, table cards with a day slot grid, Review & Confirm, Confirmed) and the `/reservations` page have no backend, so a guest cannot book a table.

**Approach:** A core feature `features/core/bookings`, because invites, cart, orders and reviews will build on it. One public search route returns table cards with their slot grid; signed-in users create, list and cancel their bookings. Double booking is prevented in the service with row locks, and a PostgreSQL exclusion constraint is the database backstop.

## Boundaries & Constraints

**Always:**
- Decisions (Vlad, 2026-11-11): the guest picks the table and the slot. Search shows tables with `party_size <= capacity <= 4`; 6- and 8-seaters are not bookable online. Party size is 1 to 4. A booking lasts 1.5 h. Slot starts every 30 min from 10:00 to 21:30 restaurant time, the same at every location. Dates from today up to 30 days ahead. Cancel until 30 min before the start. One user cannot hold two overlapping active bookings. Search is public; create, list and cancel need sign-in (`CurrentUserDep`, 401 `NOT_AUTHENTICATED`).
- These values live in a new `BookingSettings` block (`BOOKING_` prefix): `timezone` `Asia/Tbilisi`, `first_slot` 10:00, `last_slot` 21:30, `slot_minutes` 30, `duration_minutes` 90, `horizon_days` 30, `cancel_cutoff_minutes` 30, `max_online_party_size` 4 (caps both the party and the table capacity).
- Every date and grid rule uses local time in `BOOKING_TIMEZONE`: "now" is `clock.now()` converted there, a `starts_at` sent with any offset is converted before the checks, and allowed dates are `today <= date <= today + horizon_days`.
- Statuses: `CONFIRMED` (on create) and `CANCELLED` only.
- A slot is available when its start is later than now and the table has no `CONFIRMED` booking overlapping `[start, start + duration)`. Time ranges are half-open, so 12:00–13:30 and 13:30–15:00 do not overlap.
- Decision (Vlad): the booking object is the same in the create, list and cancel responses; `GET /bookings` returns a plain list of the user's bookings, every status, newest start first (ties by `id`), not paginated. There is no design for the reservations page.
- Business rules are checked in the service. Create locks the user row, then the table row (`FOR UPDATE`), in that order. An exclusion violation that slips through becomes `SLOT_UNAVAILABLE`.

**Never:** editing a booking or choosing a duration (next PR); invites, pre-order, cart; `COMPLETED` / `NO_SHOW` or staff roles; notifications, outbox or n8n; per-location or per-weekday opening hours; booking tables above `max_online_party_size`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Search, all locations | `date`, `party_size=2`, no `time` | tables with capacity 2–4 that have at least one available slot; each with its full day grid | N/A |
| Search at a time | `time=12:00` | only tables available at 12:00, each still with its full day grid | N/A |
| Horizon | `date` = today + 30 / today + 31 | 200 / nothing returned | — / 400 `DATE_OUT_OF_RANGE` |
| Nothing free | every fitting table booked at `time` | 200, `items: []`, `total: 0` | N/A |
| Today | `date` = today, now 13:10 | slots up to 13:00 unavailable | N/A |
| Bad search input | `party_size=5` / date outside today..+30 / `time` off-grid or outside 10:00–21:30 / unknown `location_id` | nothing returned | 400 `PARTY_TOO_LARGE` / 400 `DATE_OUT_OF_RANGE` / 400 `SLOT_INVALID` / 404 `LOCATION_NOT_FOUND` |
| Create | free 12:00 slot, fitting table, signed in | 201 booking, `CONFIRMED`, 12:00–13:30; starts 11:00–13:00 on that table become unavailable, 10:30 and 13:30 stay available | N/A |
| Bad create input | `party_size=5` / start off-grid or outside 10:00–21:30 / date outside today..+30 | nothing stored | 400 `PARTY_TOO_LARGE` / 400 `SLOT_INVALID` / 400 `DATE_OUT_OF_RANGE` |
| Slot taken or past | overlapping `CONFIRMED` booking, or start ≤ now | nothing stored | 409 `SLOT_UNAVAILABLE` |
| Own overlap | user already holds an overlapping `CONFIRMED` booking at any table | nothing stored | 409 `OVERLAPPING_BOOKING` |
| Wrong table | unknown table / capacity < party or > 4 | nothing stored | 404 `TABLE_NOT_FOUND` / 400 `TABLE_NOT_SUITABLE` |
| List | signed in | own bookings only, `starts_at` DESC | N/A |
| Cancel | own `CONFIRMED`, ≥ 30 min before start | 200, `CANCELLED`; the slot is available again | N/A |
| Cancel refused | another user's or unknown id / already cancelled / less than 30 min left | status unchanged | 404 `BOOKING_NOT_FOUND` / 409 `BOOKING_ALREADY_CANCELLED` / 409 `CANCELLATION_CLOSED` |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/locations/` -- `DiningTable` (`capacity`, `label`, `location_id`), `Location`, `LocationRepository.ORDERING`, `LocationCatalogService` (reuse for the location part of a card: address and `image_url`), `LocationNotFoundError`. Bookings import locations, users and auth (core to core, one way); none of them imports bookings.
- `backend/src/app/features/core/auth/endpoints/dependencies.py:204` -- `CurrentUserDep` (`UserResponse` with `id`); `auth/endpoints/errors.py` maps `NotAuthenticatedError` to 401. Document it per route like `/me` (`auth/endpoints/auth.py:302-310`). The access token expires after 15 min of `clock` time, so tests that advance the clock further must sign in again.
- `backend/src/app/common/error_responses.py` -- `error_responses()` raises `ValueError` for an error missing from the `statuses` it gets: the bookings routes pass a map that also holds `LocationNotFoundError` and `NotAuthenticatedError`.
- `backend/src/app/features/core/auth/services/registration_service.py:40-46` -- pattern for turning an `IntegrityError` into a domain error by constraint name and re-raising anything else.
- `backend/src/app/features/core/users/repositories/user_repository.py` -- `get_by_id(for_update=True)` for the user lock.
- `backend/src/app/features/core/menu/` -- page shape to copy: `dto/dish_page.py`, `endpoints/menu.py` (`limit` 1–50, default 20; `offset` bounded by bigint).
- `backend/src/app/common/clock.py` -- every "now"; tests replace it (`FakeClock` in `tests/test_login.py:44-55`).
- `backend/src/app/config/settings.py` -- add `BookingSettings` and the `booking` field on `Settings`; pass `settings.booking` to services like `settings.auth`.
- `backend/src/app/common/database.py:15` -- the naming convention has no exclusion key; name the constraint explicitly.
- `backend/tests/conftest.py:49` -- the prefixes cleared from the environment for every test.
- `backend/tests/test_database.py:359-374` -- constraint test pattern: the failing flush is the last statement, because it aborts the savepoint.
- `backend/migrations/versions/0009_create_dining_tables.py` -- migration style (`op.f` names). `0010` revises `0009`.
- `backend/src/app/main.py`, `backend/src/app/model_registry.py`, `backend/tests/test_openapi.py` -- wiring, model registry, flow tags.
- `backend/tests/test_locations.py`, `tests/test_login.py` -- client fixture, row fixtures, signing in through `POST /auth/login`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/conftest.py` -- add `"BOOKING_"` to the cleared prefixes.
- [x] `backend/tests/test_bookings.py` -- API tests for every matrix row and the error order below, against own locations and tables after clearing the migrated ones, with a fixed `FakeClock`; users are inserted verified and signed in through `/auth/login`. Include the boundary pair (12:00–13:30 then 13:30), a cancelled booking that no longer blocks the slot, and a create sent with a UTC offset that lands on the local grid.
- [x] `backend/tests/test_database.py` -- `bookings` columns, FKs with CASCADE, CHECKs, and the exclusion constraint: its `pg_get_constraintdef` (with the WHERE clause, since `alembic check` cannot see it); a `CANCELLED` overlap and adjacent ranges insert fine; two overlapping `CONFIRMED` rows raise `IntegrityError` in a test of their own, failing flush last.
- [x] `backend/tests/test_openapi.py`, `backend/tests/test_settings.py` -- "Booking" tag between "Locations" and "Health"; `BookingSettings` defaults and `BOOKING_` overrides.
- [x] `backend/migrations/versions/0010_create_bookings.py` -- `CREATE EXTENSION IF NOT EXISTS btree_gist`, enum `booking_status`, table `bookings`; downgrade drops table, enum and extension.
- [x] `backend/src/app/features/core/bookings/` -- `models/booking.py`, `enums/booking_status.py`, `repositories/`, `dto/`, `services/` (search, booking, `exceptions.py`), `schemas/`, `endpoints/` (router, dependencies, errors, `openapi_tags.py`).
- [x] `backend/src/app/config/settings.py`, `backend/src/app/model_registry.py`, `backend/src/app/main.py` -- settings block, model, router, OpenAPI tag, and the bookings `ERROR_STATUSES` merged into the app map. Every route lists its errors with `error_responses(...)` (ADR 12).
- [x] `docs/adr/0013-table-booking-slots-and-double-booking.md` -- slot model, half-open ranges, stored `ends_at`, locks plus exclusion constraint; `docs/adr/0011-feature-sliced-backend-layout.md` -- amendment: bookings are core.
- [x] `_bmad_output/implementation-artifacts/deferred-work.md` -- the lock test with two connections, as for auth, and the `IntegrityError` to `SLOT_UNAVAILABLE` branch, which one connection cannot reach because the locked check catches every overlap first.

**Acceptance Criteria:**
- Given the local server at `0010`, when a signed-in user books a free slot through curl, then search shows the starts that overlap it as unavailable on that table, and cancelling frees them.
- Given CI, then lint, mypy, import-linter, the migration round trip with `alembic check`, and tests pass.

## Design Notes

- Routes under `/api/v1/bookings`: `GET /tables` (public search: `date`, `party_size`, optional `location_id` and `time`, `limit`, `offset`), `POST ""` (201; body `table_id`, `starts_at` as an aware datetime, `party_size`), `GET ""`, `POST /{booking_id}/cancel`. Cancel is a transition, not `DELETE`.
- Search card: `id`, `label`, `capacity`, `location` (`id`, `address`, `image_url`), `slots` (`starts_at`, `available`). Booking object: `id`, `status`, `party_size`, `starts_at`, `ends_at`, `table` (`id`, `label`, `capacity`), `location` (`id`, `address`, `image_url`). All datetimes leave the API in the restaurant time zone (`+04:00`): services return DTOs (`BookingView`, `TableCardView`) whose datetimes are already converted, because asyncpg returns UTC and a freshly flushed row keeps the client's offset.
- Table `bookings`: `id` (uuid, `gen_random_uuid()`), `user_id` (FK `users`, CASCADE), `table_id` (FK `dining_tables`, CASCADE), `party_size` (int), `starts_at` and `ends_at` (`timestamptz`, which `tstzrange` needs), `status` (enum `booking_status`, server default `CONFIRMED`), `created_at` and `updated_at` as in `Location`; all NOT NULL. Exclusion constraint `ex_bookings_table_id_period`: `EXCLUDE USING gist (table_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status = 'CONFIRMED')`, via SQLAlchemy `ExcludeConstraint` (renders on SQLAlchemy 2.1.8 and Alembic 1.20.1; the default `[)` bounds are half-open). Also `CHECK (ends_at > starts_at)`, `CHECK (party_size BETWEEN 1 AND 8)`, index on `user_id`. Both times are stored, so a later duration choice needs no schema change.
- Search loads the fitting tables and the `CONFIRMED` bookings overlapping `[day first_slot, day last_slot + duration)`, builds the grids in the service and paginates in memory (about 32 tables at most). Order: location `created_at, id`, then `char_length(label), label`, so `Table 2` comes before `Table 10`.
- Error order. Search: `PARTY_TOO_LARGE`, `DATE_OUT_OF_RANGE`, `SLOT_INVALID`, `LOCATION_NOT_FOUND`. Create: `NOT_AUTHENTICATED`, `PARTY_TOO_LARGE`, `DATE_OUT_OF_RANGE`, `SLOT_INVALID`, `TABLE_NOT_FOUND`, `TABLE_NOT_SUITABLE`, `SLOT_UNAVAILABLE` for a start ≤ now, then lock the user and the table, `SLOT_UNAVAILABLE` for a table overlap, `OVERLAPPING_BOOKING`, insert and flush. Cancel: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`, `BOOKING_ALREADY_CANCELLED`, `CANCELLATION_CLOSED`. `party_size` below 1 is `Query`/body validation (`ge=1`), so 422 `VALIDATION_ERROR`.
- An `IntegrityError` naming `ex_bookings_table_id_period` becomes `SLOT_UNAVAILABLE`; any other is re-raised.
- `alembic check` cannot see exclusion constraints (no reflection), so drift is caught only by the `pg_get_constraintdef` test. `zoneinfo` needs system tzdata: present in `python:3.12-slim`, check the 3.14 image during the live run.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.
- Throwaway `postgres:18`: `alembic upgrade head`, `downgrade 0009`, `upgrade head`, `alembic check` -- clean.

## Implementation Notes

- Services: `TableSearchService` and `BookingService` take the session, `LocationCatalogService` and `settings.booking`; the grid, horizon, party and cutoff rules live in `BookingSchedule`, built from the same settings block. Table queries live in the bookings feature as `BookableTableRepository`, ordered with `LocationRepository.ORDERING`.
- `BOOKING_TIMEZONE` is typed `ZoneInfo`, so an unknown zone fails at startup. `zoneinfo` resolves `Asia/Tbilisi` in `python:3.14-slim` (checked with a throwaway container).
- The bookings routes document `NOT_AUTHENTICATED` and `LOCATION_NOT_FOUND` through `DOCUMENTED_ERROR_STATUSES`, which takes their statuses from the auth and locations maps; `main.py` merges only the bookings `ERROR_STATUSES`.
- A search `time` that carries an offset is treated as off-grid (`SLOT_INVALID`).
- Verified by the implementer: ruff, format check, mypy, lint-imports (9 kept), pytest 369 passed on the local server; throwaway `postgres:18` round trip `upgrade head`, `downgrade 0009` (extension and enum gone), `upgrade head`, `alembic check` clean. The live curl check on the local `app` database at `0010` is not done: the migration was not applied to `app`.
- Review patches (rows 15-21): four tests, ADR 13 wording, README.md / README.uk.md, `.env.example`. Verified by the orchestrator: ruff, format, mypy, lint-imports (9 kept), pytest 377 passed.
- Explanatory comments in the new code stay by Vlad's decision (2026-11-11); in general he does not want them.
- Live check 2026-11-11 (local `app` at `0010`, migrated by Vlad; clock 21:50 Tbilisi; test user `booking-check@example.com` registered and verified through the API): search for 2026-11-12, party 2 lists 32 tables (7 / 11 / 14), 24 slots 10:00–21:30 `+04:00`; booking Table 4 at Rustaveli for 12:00 answers 201 with 12:00–13:30 and the location `image_url`; its grid shows 11:00–13:00 taken, 10:30 and 13:30 free; `time=12:00` drops Table 4; the same table at 12:30 answers 409 `SLOT_UNAVAILABLE`; another table at `08:30Z` answers 409 `OVERLAPPING_BOOKING`; party 5 400 `PARTY_TOO_LARGE`; anonymous create 401; the list shows the booking; cancel answers `CANCELLED` and frees the grid; a second cancel 409 `BOOKING_ALREADY_CANCELLED`; today after the last slot gives an empty page; 2026-12-11 200, 2026-12-12 and 2026-11-10 400; unknown location 404; `time=12:15` 400 `SLOT_INVALID`. No 5xx or traceback in the server log.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | `bookings` columns, types and defaults undefined | high | Patched: Design Notes table definition, `timestamptz`. |
| 2 | spec review | Time zone of "today", horizon and grid unstated; horizon bound unclear | medium | Patched: Always rule, inclusive `today + horizon_days`, matrix row. |
| 3 | spec review | Create and list would return different offsets | medium | Patched: services return converted DTOs. |
| 4 | spec review | Order of errors when several checks fail | medium | Patched: error order per route, `ge=1` gives 422. |
| 5 | spec review | ADR 12 route docs need foreign errors in the status map | medium | `error_responses` raises on unknown errors. Patched: Code Map and wiring task. |
| 6 | spec review | `BOOKING_` env leaks into tests | medium | `tests/conftest.py:49`. Patched: task. |
| 7 | spec review | Constraint test aborts its own savepoint | low | `test_database.py:359-374`. Patched. |
| 8 | spec review | IntegrityError mapping unreachable on one connection | low | Patched: deferred-work task. |
| 9 | spec review | `alembic check` blind to exclusion constraints | low | Patched: `pg_get_constraintdef` test. |
| 10 | spec review | "Bookings of that local day" depends on no booking crossing midnight; no settings validator | low | Patched: overlap window. Validator rejected: nobody asked, a hedge. |
| 11 | spec review | List order not stable | low | Patched: ties by `id`. |
| 12 | spec review | Card grid with `time` filter unclear | low | Patched: always the full day grid. |
| 13 | spec review | Clock advance beyond 15 min expires the test session | low | `access_token_codec.py:42`. Patched: Code Map note. |
| 14 | spec review | Wrong Code Map line numbers | low | Patched: 204, 15. |
| 15 | verification-gap | Search lower capacity bound untested (all searches use party 2) | medium | Pre-verified. Patch: party 3 drops the 2-seater, party 1 keeps it. |
| 16 | verification-gap, blind | Local "today" never tested where local and UTC dates differ | medium | Pre-verified. Patch: clock at 01:00 Tbilisi, boundary dates. |
| 17 | verification-gap | Search load window end (`last_slot + duration`) untested | medium | Pre-verified. Patch: 21:30 booking shows its slot taken. |
| 18 | blind | Search `time` with an offset → `SLOT_INVALID` untested | low | Implementation Notes claim with no test. Patch: one parametrized case. |
| 19 | blind | ADR 13 says user overlap cannot be a constraint; it can (`user_id WITH =`) | low | Wrong statement in the ADR. Patch: correct the text, state the user rule has no DB backstop. Adding a second constraint is outside the spec. |
| 20 | blind | README.md / README.uk.md still list core features and flows without bookings | low | README.md:31, 67, 72; README.uk.md:66, 71. Patch. |
| 21 | blind | `backend/.env.example` has every settings block but `BOOKING_*` | low | `.env.example` lists AUTH_, TOKEN_, MEDIA_ with defaults. Patch. |
| 22 | edge, blind | Downgrade drops `btree_gist` it may not have created | false | Local `app` has only `plpgsql`; databases are created by compose and only 0010 creates the extension. |
| 23 | edge | User or table deleted / capacity changed between read and lock | false | No write path deletes users or changes tables; tables come only from migrations. |
| 24 | edge | Location committed between `list_all` and `list_fitting` → KeyError | false | Locations are written only by migrations. |
| 25 | edge | `starts_at` near `datetime.min/max` → `OverflowError` 500 | low | Real for crafted input only; the fix adds a guard branch. Rejected. |
| 26 | edge | No settings validator | low | carried #10: rejected. |
| 27 | blind | Live curl check not done | false | Not a code defect: it needs `alembic upgrade head` on `app`, which waits for Vlad's go-ahead. |
| 28 | blind | Roadmap item "Table booking" not ticked | false | The item covers booking as a whole; editing is still to come. |
| 29 | blind | n8n roadmap rewrite does not belong in this branch | false | Vlad asked for it in this branch. Isolating the simulator from real guests is for its own spec. |
| 30 | blind | Clients cannot learn horizon, party cap, cutoff; messages carry no numbers | low | backend.md: descriptions name limits without numbers; the spec asked for no settings route. Rejected. |
| 31 | blind | `list_all()` / `get()` count tables on every booking request | low | Three locations; a leaner method adds public surface. Rejected. |

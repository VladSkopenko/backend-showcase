---
title: 'Staff role and request decisions'
type: 'feature'
created: '2026-11-13'
status: 'done'
baseline_commit: 'a34586d41c92de1104876c5f9ef02b21e8bfaaf2'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/1-large-party-booking-requests.md'
  - '{project-root}/docs/adr/0013-table-booking-slots-and-double-booking.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Large-party requests (story 1) stay `PENDING` forever: nobody can approve or reject them, and nothing records how fast staff answer.

**Approach:** Users get an `is_staff` flag. Staff routes under `/staff/booking-requests` list pending requests and approve or reject one. Approving confirms the request and rejects the other pending requests that overlap it on the same table. Each decision stores when and by whom it was made, for the staff dashboard (story 9).

## Boundaries & Constraints

**Always:**
- `users.is_staff` (default false) is the only role; set by migrations or SQL by an operator, never through the API.
- Data migration `0018` creates the staff bot `waiter-bot@example.com` (first name Waiter, last name Bot, verified, `is_staff` true, the bot password hash of `0011`) when `APP_ENVIRONMENT` is `dev` or `local`; elsewhere upgrade and downgrade do nothing; downgrade deletes it. A plain insert: an existing email fails loudly (Vlad, 2026-11-13).
- Staff routes answer 401 `NOT_AUTHENTICATED` without a session and 403 `STAFF_ONLY` for a non-staff user. The check lives in the service.
- New status `REJECTED`; it is inactive by the existing active rule. `bookings.decided_at` and `bookings.decided_by_id` (FK users, `ON DELETE SET NULL`) are set on every approve and reject, including the requests rejected by an approval.
- Approve: lock the table, then the request (ADR 13 order). Only a `PENDING` request whose start is in the future can be approved. If the table has a confirmed overlap, answer `SLOT_UNAVAILABLE` and leave the request pending. Otherwise set `CONFIRMED`, then set `REJECTED` on every other `PENDING` request on that table whose period overlaps. The exclusion constraint stays the backstop.
- Reject: lock the request; only `PENDING`; set `REJECTED`.
- The owner of a rejected request gets `BOOKING_REJECTED` (409) on cancel, edit and edit slots, and on the invite link; joining answers `INVITE_CLOSED` as for any inactive booking. A rejected request frees the user's time.
- The staff list shows future `PENDING` requests ordered by start, then by creation: id, owner first name, party size, start and end, created at, table, location, and the number of other pending requests competing for that table and time. `limit` 20 by default, at most 50, `offset`.
- New OpenAPI tag `Staff`, after `Preorder`.
- An approved large booking (confirmed, on a table above the instant limit) cannot be changed: edit and edit slots answer 409 `LARGE_BOOKING_NOT_EDITABLE`; the guest may only cancel it and send a new request (Vlad, 2026-11-13).

**Never:** Notifications (story 3), auto-reject (story 4), guest bots (story 5), staff management through the API, finer roles.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| List | staff; pending requests on two tables, one past | 200, future ones by start then creation, competing counts | N/A |
| Approve | staff; pending request, free table, a competing request | 200 `CONFIRMED`; competitor `REJECTED`; both have `decided_at`, `decided_by_id` | N/A |
| Approve, table taken | a confirmed booking now overlaps on that table | request stays `PENDING` | 409 `SLOT_UNAVAILABLE` |
| Approve twice | request already `CONFIRMED`, `REJECTED` or `CANCELLED`, or a plain booking | unchanged | 409 `REQUEST_NOT_PENDING` |
| Approve past start | pending request whose start has passed | unchanged | 409 `REQUEST_EXPIRED` |
| Reject | staff; pending request | 200 `REJECTED` | N/A |
| Not staff | signed-in user on any staff route | nothing changes | 403 `STAFF_ONLY` |
| Unknown id | approve or reject | nothing changes | 404 `BOOKING_NOT_FOUND` |
| Owner after reject | cancel, edit, invite link | unchanged | 409 `BOOKING_REJECTED` |
| Owner after reject | books an overlapping slot | 201 | N/A |
| Owner after approve | pre-order a dish | 200 | N/A |
| Owner after approve | edit or edit slots of the approved booking | unchanged | 409 `LARGE_BOOKING_NOT_EDITABLE` |
| Owner after approve | cancel the approved booking | 200 `CANCELLED` | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/users/models/user.py` -- `User`: add `is_staff`.
- `backend/src/app/features/core/bookings/models/booking.py` -- `Booking`: `decided_at`, `decided_by_id` (second FK to users: explicit `foreign_keys=` where relationships exist, backend.md).
- `backend/src/app/features/core/bookings/enums/booking_status.py` -- add `REJECTED`; `active()` unchanged.
- `backend/migrations/versions/0017_add_staff_and_request_decisions.py` -- new: `users.is_staff` (server default false), `ALTER TYPE booking_status ADD VALUE 'REJECTED'`, the two booking columns; downgrade turns `REJECTED` into `CANCELLED`, drops columns, rebuilds the type keeping `PENDING` (pattern: `0016` downgrade, default and exclusion constraint included).
- `backend/src/app/features/core/bookings/services/booking_request_service.py` -- new `BookingRequestService` (list, approve, reject; builds its repositories from the session; loads the staff user to check `is_staff`).
- `backend/src/app/features/core/bookings/repositories/booking_repository.py` -- reuse `get(booking_id, for_update=)` (l.119), `table_has_confirmed_overlap`; add the pending list, the competing count and the bulk reject of overlapping pending requests on a table.
- `backend/src/app/features/core/bookings/repositories/bookable_table_repository.py` -- `get(table_id, for_update=True)` (l.32) for the table lock.
- `backend/src/app/features/core/bookings/services/booking_service.py` (cancel l.107, `_get_editable` l.198), `participant_service.py` (`lock_owned` l.60) -- one helper raises `BOOKING_ALREADY_CANCELLED` for `CANCELLED` and `BOOKING_REJECTED` for `REJECTED`.
- `backend/src/app/features/core/bookings/dto/` -- `BookingRequestView` (fields above plus `status`).
- `backend/src/app/features/core/bookings/services/exceptions.py`, `endpoints/errors.py` -- `StaffOnlyError` 403, `RequestNotPendingError` 409, `RequestExpiredError` 409, `BookingRejectedError` 409, `LargeBookingNotEditableError` 409 (raised in `_get_editable` when the table capacity is above the instant limit).
- `backend/src/app/features/core/bookings/endpoints/booking_requests.py`, `schemas/`, `dependencies.py`, `openapi_tags.py`, `backend/src/app/main.py` (l.51-58 tags, l.72-79 routers) -- the three routes, tag `Staff`.
- Tests: `tests/support/booking_fixtures.py` `users` (l.59) has no staff; add a staff user fixture there. `tests/test_openapi.py` `FLOWS` gets `Staff`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_booking_request_decisions.py` -- new; one test per matrix row, first and failing -- contract.
- [x] `backend/tests/support/booking_fixtures.py`, `tests/test_openapi.py`, `tests/test_database.py` -- staff fixture, `Staff` flow, enum labels and new columns -- pins.
- [x] `backend/migrations/versions/0017_add_staff_and_request_decisions.py` -- schema.
- [x] Models, enum, repository, `BookingRequestService`, DTO, the inactive-status helper in booking and participant services -- behaviour.
- [x] Exceptions, error map, schemas, routes, dependencies, tag, `main.py` -- API.
- [x] `docs/adr/0013-table-booking-slots-and-double-booking.md` -- amend: decisions, lock order of approve, `REJECTED`, staff flag -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass; CI's `upgrade head`, `downgrade base`, `upgrade head` succeed.
- Given a local API at 0017 and a staff user, when two users request one table and time and staff approve one, then one is `CONFIRMED`, the other `REJECTED`, and the slot shows taken in search.

### Review Findings

Code review 2026-11-13 (bmad-code-review: blind, edge-case, verification-gap, acceptance layers).

- [x] [Review][Patch] 0018 gate untested for staging and prod; downgrade untested [backend/tests/test_staff_bot_migration.py]
- [x] [Review][Patch] Reject untested on confirmed, cancelled and plain bookings [backend/tests/test_booking_request_decisions.py]
- [x] [Review][Patch] Staff list `offset` bigint bound not pinned [backend/tests/test_booking_request_decisions.py]
- [x] [Review][Patch] Invite link description omits cancelled and rejected answers [backend/src/app/features/invites/endpoints/invites.py]
- [x] [Review][Patch] Staff tag text says only an operator flags staff [backend/src/app/features/core/bookings/endpoints/openapi_tags.py]
- [x] [Review][Patch] ADR 14 does not record the staff bot and its local scope [docs/adr/0014-booking-simulator-on-dev.md]
- [x] [Review][Defer] 0017 downgrade with data has no pytest — deferred: already in deferred-work.md; checked manually

Rejected:
- Approve inside the cancel window gives a booking the guest cannot cancel: low; story 4 auto-rejects requests 2 hours before start, so none stay pending that late.
- 0018 fails on a taken email: false; the spec asks for a loud failure.
- Live check and round trip not done: false; both done by the parent session (Implementation Notes).
- Overlap rule and exclusion-constraint mapping duplicated: low; refactor beyond a direct fix.
- No concurrency test for approve's lock order: low; heavy to build, the backstop path is tested.
- Competing count with started competitors, cascade over started competitors, settings change after bookings: low, repeated from the first review.

## Implementation Notes

- 2026-11-13: implemented by a fresh subagent from this spec; 583 tests, ruff, mypy, lint-imports clean. Migration checked on a throwaway Postgres 18: a stored `REJECTED` row becomes `CANCELLED` on downgrade to 0016 (a `PENDING` row stays), labels, default and exclusion constraint match 0016, the columns are gone; `upgrade head`, `downgrade base`, `upgrade head` and `alembic check` succeed.
- The list answers the project's page envelope (`items`, `total`, `limit`, `offset`), as the dish and table searches do; the competing count field is `competing_requests`. Ties after start and creation break by id.
- The shared inactive check is `services/inactive_booking_guard.py` (`InactiveBookingGuard`); `BookingSchedule.is_request_table` names the "table above the instant limit" rule used by `_get_editable`.
- Tags: `BookingOpenApiTags.STAFF` with its own `STAFF_METADATA`, passed after Pre-order in `create_app`; the router is exported as `staff_router`.
- Beyond the Code Map: `BookingRejectedError` is documented on the invite link route; descriptions of edit, edit slots, invite preview and join, and the `INVITE_CLOSED` message mention rejection.
- Review fixes: index `ix_bookings_decided_by_id` (model and 0017); tests for the exclusion backstop of approve, status filters of the list and competing count, the owner's list after approve and reject, anonymous reject; cancel and edit descriptions mention `BOOKING_REJECTED`. The round trip was not re-run after the index was added.
- Migration 0018 (staff bot, `dev` and `local` only): pinned by `tests/test_staff_bot_migration.py`; `tests/test_google_oauth.py` counts users other than the bot (`WAITER_BOT` in `tests/support/bookings.py`), since the test database is migrated as `local`. The migration round trip was not re-run with 0018.
- 2026-11-13, verified by the parent session: 585 tests; round trips on a throwaway Postgres with 0018 and the index (`upgrade head`, `downgrade base`, `upgrade head`, `alembic check`; 0018 inserts the bot under `local` and nothing under `staging`). Live curl on the local API at 0018 with `waiter-bot@example.com`: STAFF_ONLY for a guest, list with competing counts, approve confirms one request and rejects the other, the slot is taken in search, REQUEST_NOT_PENDING, LARGE_BOOKING_NOT_EDITABLE, BOOKING_REJECTED, cancel of the approved booking; decisions stored.

## Spec Change Log

- 2026-11-13, after review: Vlad moved the staff bot from story 5 into this story so the staff routes have a user on dev and locally; migration 0018 added to the frozen intent. KEEP: everything implemented so far.
## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| 0017 downgrade with a REJECTED row has no pytest (verification-gap) | low | Checked manually on a throwaway Postgres: row becomes CANCELLED, labels, default and constraint match 0016. | defer (no downgrade-with-data harness) |
| Competing count includes competitors whose start passed (edge-case) | low | Those are exactly the rows an approval rejects; the count is consistent with approve. | rejected |
| List total and items read in two queries (edge-case) | low | Only a concurrent decision between the queries skews paging. | rejected |
| Staff can decide their own request (edge-case, blind) | low | True; the spec does not forbid it; raised to Vlad. | rejected, raised |
| Past PENDING requests leave the list but stay pending (edge-case) | low | Auto-reject is story 4 by intent. | rejected: out of scope by intent |
| Edit guard uses the current instant limit (edge-case) | low | Only a later settings change reaches it. | rejected |
| Cascade rejections look like staff rejections (blind) | medium | `reject_pending_overlapping` stamps the approver and approval time. | defer to story 9 |
| decided_at and created_at use different clocks (blind) | low | App clock vs DB now(); seconds apart at most. | rejected |
| Reject has no start-time guard (blind) | low | Rejecting a past request is harmless cleanup. | rejected |
| No index on decided_by_id (blind) | low | FK with SET NULL scans bookings on user delete. | patch: index added |
| is_staff and editability not exposed to clients (blind) | low | New public surface; no client needs it yet. | rejected |
| No way to create a staff user outside tests (blind) | low | Superseded: Vlad moved the staff bot into this story (migration 0018). | resolved by 0018 |
| Approve IntegrityError backstop untested (blind) | low | No test reached the branch. | patch: test added |
| List and competing status filters under-tested (blind) | low | Only PENDING competitors were seeded. | patch: test extended |
| Owner list after decisions and anonymous reject untested (blind) | low | No such assertions. | patch: tests added |
| Cancel and edit descriptions omit the rejected state (blind) | low | Texts read as described. | patch |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

**Manual checks (if no CLI):**
- Migration round trip with a stored `REJECTED` row on a throwaway Postgres; live curl on the local API after Vlad migrates `app` to 0017 and flags a staff user.

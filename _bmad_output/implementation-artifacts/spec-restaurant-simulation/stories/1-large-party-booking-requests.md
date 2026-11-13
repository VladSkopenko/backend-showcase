---
title: 'Large-party booking requests'
type: 'feature'
created: '2026-11-13'
status: 'done'
baseline_commit: 'bf81f97a887c6190d0e76ebe8d6e8355daa586b4'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/docs/adr/0013-table-booking-slots-and-double-booking.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Online booking stops at 4 people; tables for 6 and 8 cannot be booked at all, so large parties and the staff-approval flow of the restaurant simulation have nothing to start from.

**Approach:** `POST /bookings` with a party of 5 to 8 creates a booking in a new status `PENDING` instead of `CONFIRMED`. A pending request never blocks a table; several requests may compete for one table and time, and staff decide later (story 2).

## Boundaries & Constraints

**Always:**
- Instant bookings keep today's rules: party 1 to `max_online_party_size` (4) on tables of capacity up to 4, status `CONFIRMED`.
- Requests: party `max_online_party_size + 1` to `max_request_party_size` (new setting, default 8, validated `<= 8` to match the DB CHECK), table capacity from party size up to `max_request_party_size`. Tables of 5 to 8 seats are request-only and never compete with instant bookings.
- Table overlap (service check, `ex_bookings_table_id_period`, search grids) counts only `CONFIRMED`. A request on a table with a confirmed overlap fails with `SLOT_UNAVAILABLE`.
- User overlap counts `CONFIRMED` and `PENDING`, on create and edit: a user cannot hold a request and a booking (or two requests) that overlap.
- Same endpoint and response shape; `status` is `PENDING` for a request. Date, slot, horizon, closing and lock-order rules stay as for bookings.
- A pending request can be cancelled like a booking (same cutoff); it cannot be edited (`BOOKING_PENDING`, 409). Edit keeps the instant limit (party up to `max_online_party_size`), so it never turns a booking into a request.
- Pre-order stays closed while pending (`PREORDER_CLOSED`); invites and joining work as for a booking; the invite preview shows `status`.
- One "active" rule (`CONFIRMED` or `PENDING`) replaces the `== CANCELLED` checks in cancel, edit, invite and join, so story 2 only extends it with `REJECTED`.
- Downgrade of 0016 destroys no rows: `PENDING` becomes `CANCELLED`.

**Never:** Approving or rejecting requests, `REJECTED` status, notifications, auto-reject (stories 2 to 4). Combining tables or parties above 8. Changing the exclusion constraint's definition.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Request | party 6, free 6-seat table | 201, `status: PENDING` | N/A |
| Competing requests | two users, same 8-seat table and start | both 201 `PENDING` | N/A |
| Confirmed overlap | party 6 on a table with a confirmed overlap | nothing stored | 409 `SLOT_UNAVAILABLE` |
| Too large | party 9 | nothing stored | 400 `PARTY_TOO_LARGE` |
| Table too small | party 5 on a 4-seat table | nothing stored | 400 `TABLE_NOT_SUITABLE` |
| Instant on big table | party 4 on a 6-seat table | nothing stored | 400 `TABLE_NOT_SUITABLE` |
| User overlap | user with a pending request books, or edits a booking into, an overlapping slot | unchanged | 409 `OVERLAPPING_BOOKING` |
| Search | `GET /bookings/tables?party_size=6` | 6- and 8-seat tables; pending requests leave slots free | N/A |
| Edit pending | `PUT /bookings/{id}` on a request | unchanged | 409 `BOOKING_PENDING` |
| Cancel pending | `POST /bookings/{id}/cancel` | 200, `CANCELLED` | N/A |
| Pre-order pending | `PUT /bookings/{id}/cart/items/{dish}` | unchanged | 409 `PREORDER_CLOSED` |
| Join pending | invite preview and join of a request | 200; preview `status: PENDING` | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/bookings/enums/booking_status.py` -- add `PENDING` and the "active" rule (`CONFIRMED`, `PENDING`).
- `backend/src/app/config/settings.py` -- `BookingSettings` (l.128): `max_request_party_size` with `le=8`; the comment on `max_online_party_size` (l.138) no longer says larger tables are offline.
- `backend/src/app/features/core/bookings/services/booking_schedule.py` -- `check_party_size` (l.57) stays the instant check used by edit; add the request-aware check and the capacity ceiling per party size, used by create and search.
- `backend/src/app/features/core/bookings/services/booking_service.py` -- `create` (l.46-95): status and ceiling from the schedule, active user overlap; `cancel` (l.107) and `_get_editable` (l.198): active rule, `PENDING` raises `BookingPendingError`; edit (l.126-148) keeps its party check and uses the active user overlap.
- `backend/src/app/features/core/bookings/repositories/booking_repository.py` -- `user_has_confirmed_overlap` (l.54) becomes `user_has_active_overlap`; `_confirmed_overlapping` (l.165) and table checks stay `CONFIRMED`.
- `backend/src/app/features/core/bookings/services/table_search_service.py` -- request-aware party check (l.38) and ceiling for `list_fitting` (l.45-49).
- `backend/src/app/features/core/bookings/services/participant_service.py` -- `lock_owned` (l.60) and `_check_joinable` (l.195): active rule; `preview` (l.66-77) adds `status`; `dto/invite_preview_view.py` and `features/invites/schemas/invite.py` `InvitePreviewResponse` add `status`.
- `backend/src/app/features/core/bookings/services/exceptions.py`, `endpoints/errors.py` -- `BookingPendingError`, `BOOKING_PENDING`, 409.
- `backend/src/app/features/preorder/services/exceptions.py` (l.8) and `endpoints/preorder.py` descriptions (l.78, 115, 151) -- closed also while the booking awaits confirmation.
- `backend/src/app/features/core/bookings/endpoints/bookings.py` -- descriptions of `POST /bookings`, `GET /bookings/tables`, `PUT /bookings/{id}`.
- `backend/migrations/versions/0016_add_pending_booking_status.py` -- upgrade: `ALTER TYPE booking_status ADD VALUE 'PENDING'`. Downgrade: `UPDATE ... SET status='CANCELLED' WHERE status='PENDING'`, drop the `status` default and `ex_bookings_table_id_period`, rebuild the type (rename, create, `ALTER COLUMN ... USING status::text::booking_status`, drop old), restore the default `'CONFIRMED'` and the constraint with its 0010 definition (0010 l.65-71). Pattern for the rebuild: `0004_add_password_reset.py` l.43-51.
- Tests: `tests/support/bookings.py` (`book`, `sign_in`, `add_booking(status=...)`, `assert_error`), `booking_fixtures.py` (`venue`: tables 2, 4, 6, 8), settings override as in `test_bookings.py` l.44-49.
- Do not change: the exclusion constraint's definition, `list_for_user`, the CHECK `party_size_between_1_and_8`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_booking_requests.py` -- new; one test per matrix row, written first and failing -- pins the contract.
- [x] `backend/tests/test_bookings.py` -- party 5 used as "too large" for create and search (l.265, 292, 526-528, and the same pattern elsewhere) becomes 9; edit keeps 5 -- the limit moved.
- [x] `backend/tests/test_database.py` (l.433-436), `tests/test_settings.py` -- enum labels with `PENDING`; the new setting and its bound -- pins.
- [x] `backend/migrations/versions/0016_add_pending_booking_status.py` -- as in Code Map -- schema.
- [x] Settings, enum, schedule, booking service, repository, search, participant service, DTO and schema -- rules above -- behaviour.
- [x] Exceptions, error mapping, booking and pre-order route descriptions -- API.
- [x] `docs/adr/0013-table-booking-slots-and-double-booking.md` -- amend: requests, overlap per status, the active rule -- decision record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all tests pass.
- Given CI, when it runs `alembic upgrade head`, `downgrade base`, `upgrade head`, then all succeed.
- Given a local API at 0016, when a user posts a party of 6 on a 6-seat table, then the response is 201 `PENDING` and the slot stays free in `GET /bookings/tables`.

### Review Findings

Code review 2026-11-13 (bmad-code-review: blind, edge-case, verification-gap, acceptance layers).

- [x] [Review][Patch] `.env.example` lacks `BOOKING_MAX_REQUEST_PARTY_SIZE`; its comment on the online limit is stale [backend/.env.example:49]
- [x] [Review][Patch] Invite link route still says "confirmed booking" though requests get links too [backend/src/app/features/invites/endpoints/invites.py:43]
- [x] [Review][Patch] Invite preview description does not mention `status` (only CONFIRMED or PENDING reach it) [backend/src/app/features/invites/endpoints/invites.py:66]
- [x] [Review][Patch] `PartyTooLargeError` text "cannot be booked here" is vague, worst on edit of a party of 5 [backend/src/app/features/core/bookings/services/exceptions.py]
- [x] [Review][Patch] `BookingPendingError` says "cannot be changed" though a request can be cancelled [backend/src/app/features/core/bookings/services/exceptions.py]
- [x] [Review][Patch] Search description "the tables taken by request" reads as tables already taken [backend/src/app/features/core/bookings/endpoints/bookings.py:62]
- [x] [Review][Patch] ADR 13 states request-only tables as an invariant; it holds only with the default limits [docs/adr/0013-table-booking-slots-and-double-booking.md]
- [x] [Review][Patch] ADR 13 leaves unclear that story 2 generalises `BOOKING_ALREADY_CANCELLED` together with `REJECTED` [docs/adr/0013-table-booking-slots-and-double-booking.md]
- [x] [Review][Patch] User overlap untested in the other direction: booking first, then an overlapping request [backend/tests/test_booking_requests.py]
- [x] [Review][Patch] Withdrawn request untested: frees the user's time; repeated cancel, edit and slots answer `BOOKING_ALREADY_CANCELLED` [backend/tests/test_booking_requests.py]
- [x] [Review][Patch] Search boundary untested: `party_size=5` lists 6- and 8-seat tables, not the 4-seat one [backend/tests/test_booking_requests.py]
- [x] [Review][Defer] No pytest covers the 0016 downgrade [backend/migrations/versions/0016_add_pending_booking_status.py] — deferred: the repo has no downgrade test harness; checked manually on a throwaway Postgres with a stored PENDING row

Rejected:
- Pre-order test does not assert the cart stayed unchanged: low; the closed check runs before any dish lookup, so nothing can change.
- No cross-check between `max_online_party_size` and `max_request_party_size`: low; only a misconfigured env reaches it and the fix adds a validator.

## Implementation Notes

- 2026-11-13: implemented by a fresh subagent from this spec; 556 tests, ruff, mypy, lint-imports clean. Migration round trip (0015 -> 0016 -> 0015, then base -> head) checked on a throwaway Postgres: default and exclusion constraint identical after downgrade. Beyond the Code Map: the cancel route description, and `BOOKING_PENDING` documented on `GET /bookings/{id}/slots` too (it shares `_get_editable`).
- For story 5: Alembic runs all revisions in one transaction (`migrations/env.py` l.27, 33). A data migration in the same `upgrade head` run cannot insert `PENDING` rows on a fresh database ("unsafe use of new enum value").
- For story 2: extend only the active rule with `REJECTED`; editing an approved large booking is decided there.

## Spec Change Log

- Independent review (2026-11-13) before approval: downgrade order for the default and the partial constraint, no row deletion; existing tests that use party 5 as "too large"; explicit edit rule; no downgrade test in pytest (CI covers it); pre-order text and invite preview status; the active rule; setting bound; Code Map line fixes.

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Downgrade never run with a PENDING row (verification-gap) | low | Checked manually on a throwaway Postgres: a stored PENDING row becomes CANCELLED, labels back to two, upgrade again succeeds. | resolved by manual check |
| Settings do not tie request limit to instant limit, no ge=1 (blind, edge-case) | low | Only a misconfigured env reaches it; fix adds a model validator. | rejected |
| Party 5 lower edge of requests untested (blind) | low | Only party 6 tested PENDING; an off-by-one in `_is_request` passed. | patch: test added |
| Cancel description says a request frees its table, split string (blind) | low | Text read as described. | patch |
| Edit description ambiguous, split string; slots description not updated, untested (blind) | low | Confirmed at bookings.py slots route. | patch: texts and test |
| PartyTooLarge and OverlappingBooking messages untrue for new cases (blind) | low | Messages read "call the restaurant" and "booking" only. | patch |
| Search gives no request signal to the client (blind) | low | Frontend does not call the booking API yet; adding a field is new public surface. | rejected, noted for the frontend work |
| ADR overstates that call sites need no change (blind) | low | Inactive checks raise BOOKING_ALREADY_CANCELLED. | patch: ADR wording |
| Single-transaction migration trap only in spec notes (blind) | low | env.py runs all revisions in one transaction. | patch: migration comment |
| Cancel of a request after cutoff untested (blind) | low | No such test existed. | patch: test added |
| Search with a confirmed booking on a big table untested (blind) | low | Only the pending side was checked. | patch: test extended |
| Past PENDING requests never expire (edge-case) | low | The intent puts auto-reject in story 4. | rejected: out of scope by intent |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

**Manual checks (if no CLI):**
- Live curl on the local API after Vlad migrates `app` to 0016: request for 6, competing request, search grid.

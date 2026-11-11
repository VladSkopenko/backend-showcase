---
title: 'Edit a booking: time, party size and duration'
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

**Problem:** The Figma "Edit reservation" form (time, guests, "How long would you like to stay?" 1.5 / 2 / 2.5 / 3 h) has no backend: a booking can only be cancelled and made again, and its length is always 1.5 h.

**Approach:** In the core bookings feature, one route replaces the editable fields of the signed-in user's own `CONFIRMED` booking, and one route lists the starts that booking can move to for a chosen duration. The rules of creation apply to the new values, the booking itself is ignored in the overlap checks, and the locks keep the ADR 13 order.

## Boundaries & Constraints

**Always:**
- Decisions (Vlad, 2026-11-10/11): edit keeps the table and the local day; it is allowed until the cancel cutoff (30 min before the current start, the same `cancel_cutoff_minutes`); durations are 1.5, 2, 2.5 and 3 h; the restaurant closes at 23:00 and a booking must end by closing.
- New settings in `BookingSettings`: `max_duration_minutes` 180 and `closing_time` 23:00. Allowed durations run from `duration_minutes` to `max_duration_minutes` in steps of `slot_minutes`.
- The new start follows the creation rules: on the grid (`SLOT_INVALID`), later than now (`SLOT_UNAVAILABLE`), `party_size` 1 to `max_online_party_size` (`PARTY_TOO_LARGE`) and not above the table capacity (`TABLE_NOT_SUITABLE`).
- Overlap checks exclude the edited booking: the table must be free for the new `[start, start + duration)` (`SLOT_UNAVAILABLE`), and the user must hold no other overlapping `CONFIRMED` booking (`OVERLAPPING_BOOKING`).
- Locks: user row, then table row, then booking row (`FOR UPDATE`), so edit never waits crosswise with create or cancel. Status and cutoff are checked again under the lock.
- `ends_at` is stored as `start + duration`; the response is the same booking object as create, list and cancel.
- Decision (Vlad, 2026-11-11, Figma "Edit Reservation": a Time dropdown next to the duration dropdown): the form gets its time options from the backend. The slots route returns the booking's day grid on its table for a given `duration_minutes`; a start is available when it is later than now, the stay ends by closing, and the table has no other `CONFIRMED` booking overlapping it. It refuses like edit: `BOOKING_NOT_FOUND`, `BOOKING_ALREADY_CANCELLED`, `EDIT_CLOSED`, `DURATION_INVALID`. Like search, it ignores the user's other bookings; edit still refuses those with `OVERLAPPING_BOOKING`.
- Closing is enforced by edit and by every day grid (search and slots), through one shared availability rule. Create is unchanged: with the default settings its 1.5 h from the last slot ends exactly at closing. No settings validator.
- The new start's day is compared in restaurant time: `to_local(new_start).date() == to_local(booking.starts_at).date()`.

**Never:** moving to another table or day; choosing a duration at creation; participants, invites or pre-order rules (next PR); per-location or per-weekday hours; a schema migration.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Longer stay | own 12:00–13:30, duration 180 | 200, 12:00–15:00; starts 13:30–14:30 on that table become unavailable | N/A |
| Move | own 12:00–13:30, start 14:00, duration 90, party 2 | 200, 14:00–15:30; 12:00 free again | N/A |
| Boundaries | start 21:30, duration 90 (ends 23:00) / current start exactly 30 min ahead | 200 / 200 | N/A |
| Over itself | new range overlaps only the old one | 200 | N/A |
| Party change | party 2 → 4 on a 4-seater / on a 2-seater | 200 / nothing changed | — / 400 `TABLE_NOT_SUITABLE` |
| Past closing | start 21:00, duration 150 (ends 23:30) | nothing changed | 400 `ENDS_AFTER_CLOSING` |
| Bad input | duration 100 or 210 / start on another local day / off-grid start / party 5 | nothing changed | 400 `DURATION_INVALID` / 400 `DAY_CHANGE_NOT_ALLOWED` / 400 `SLOT_INVALID` / 400 `PARTY_TOO_LARGE` |
| Taken | another booking on the table overlaps the new range | nothing changed | 409 `SLOT_UNAVAILABLE` |
| Own overlap | user holds another overlapping booking at another table | nothing changed | 409 `OVERLAPPING_BOOKING` |
| Refused booking | unknown or foreign id / cancelled / less than 30 min to the current start | nothing changed | 404 `BOOKING_NOT_FOUND` / 409 `BOOKING_ALREADY_CANCELLED` / 409 `EDIT_CLOSED` |
| Slots for a longer stay | booking tomorrow, own 12:00–13:30, other booking 15:00–16:30, duration 180 | 10:00–12:00 available (own booking ignored; 12:00 ends exactly at 15:00); 12:30–16:00 unavailable; 16:30–20:00 available; 20:30 and later unavailable (past closing) | N/A |
| Slots refused | unknown or foreign id / cancelled / cutoff passed / duration 100 | no grid | 404 `BOOKING_NOT_FOUND` / 409 `BOOKING_ALREADY_CANCELLED` / 409 `EDIT_CLOSED` / 400 `DURATION_INVALID` |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/bookings/services/booking_service.py` -- `create` and `cancel` show the check order, the lock calls, the `IntegrityError` → `SLOT_UNAVAILABLE` mapping by `EXCLUSION_CONSTRAINT`, and `_to_view`. Add `edit` here.
- `backend/src/app/features/core/bookings/services/booking_schedule.py` -- grid, party, date and cutoff checks; add the duration and closing checks here, built from the same settings.
- `backend/src/app/features/core/bookings/services/table_search_service.py:93-97` -- `_is_free` is private and uses the fixed duration. Move the rule to `BookingSchedule.is_free(start, duration, bookings, now)`, with the closing check, and use it from search and slots. Slots live on `BookingService` (they need `get_for_user`) and load bookings with `list_confirmed_overlapping(table_ids=[table], first start, last start + duration, excluding the booking)`; they return `list[SlotView]` as `list[SlotResponse]`.
- `backend/src/app/features/core/bookings/endpoints/openapi_tags.py` -- the tag description says "creating, listing and cancelling"; add editing.
- `backend/src/app/features/core/bookings/repositories/booking_repository.py` -- `table_has_confirmed_overlap`, `user_has_confirmed_overlap`, `list_confirmed_overlapping` and `get_for_user(for_update=...)`; the overlap queries need an optional booking id to exclude. The locked read must add `execution_options(populate_existing=True)`, as `auth/repositories/refresh_token_repository.py:18-21` does: `FOR UPDATE` alone keeps the stale object from the first unlocked read, so the re-check would miss a cancel that committed meanwhile.
- `backend/src/app/features/core/bookings/repositories/bookable_table_repository.py` -- `get(for_update=True)` for the table lock; `UserRepository.get_by_id(for_update=True)` for the user lock.
- `backend/src/app/features/core/bookings/services/exceptions.py`, `endpoints/errors.py`, `endpoints/bookings.py`, `schemas/booking.py` -- new domain errors, their statuses, the route with `error_responses(...)` and `description` (ADR 12, backend.md "API docs"), the request schema.
- `backend/src/app/config/settings.py:130` -- `BookingSettings`; `backend/.env.example:41-49` lists every `BOOKING_` key.
- `backend/tests/test_bookings.py` -- fixtures `fake_clock`, `venue`, `users`, helpers `sign_in`, `add_booking`, `book`, `availability`, `assert_error`, `stored_status`; reuse them, do not duplicate. `add_booking` (157-176) always stores the default duration: extend it with a duration argument. The sign-in parametrize at 659 gets both new routes.
- `backend/tests/test_openapi.py:36` -- routes pinned to the "Booking" tag; `backend/tests/test_settings.py:245-277` -- booking defaults and env overrides.
- Not to change: the exclusion constraint, migration `0010`, the create and cancel behaviour.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_bookings.py` -- API tests for every matrix row, the error order below, an edit whose new range overlaps only its old one, a cancelled booking that no longer blocks the new range, 10:00 local sent as `-08:00` of the previous date (200) and an offset that lands on the next local day (`DAY_CHANGE_NOT_ALLOWED`) -- tests first.
- [x] `backend/tests/test_settings.py`, `backend/tests/test_openapi.py` -- the two new settings with defaults and `BOOKING_` overrides; both new routes under "Booking".
- [x] `backend/src/app/config/settings.py`, `backend/.env.example` -- `max_duration_minutes`, `closing_time`.
- [x] `backend/src/app/features/core/bookings/` -- schedule checks, repository exclusion argument, `BookingService.edit` and the slots query, exceptions, error statuses, request schema, both routes.
- [x] `docs/adr/0013-table-booking-slots-and-double-booking.md` -- amendment: edit takes user, table, booking locks in that order; durations and closing time.
- [x] `_bmad_output/implementation-artifacts/deferred-work.md` -- extend the create lock-test entry to the three edit locks and `populate_existing`, and add the edit `IntegrityError` → `SLOT_UNAVAILABLE` branch; one shared connection cannot reach either.

**Acceptance Criteria:**
- Given the local server, when a signed-in user extends a booking to 3 h through curl, then search shows the extra starts on that table as unavailable, and editing back to 1.5 h frees them.
- Given CI, then lint, mypy, import-linter and tests pass.

## Design Notes

- Route `PUT /api/v1/bookings/{booking_id}`, body `starts_at` (aware datetime), `party_size` (`ge=1`), `duration_minutes`; all required, because the form always sends the three fields.
- Error order: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`, `BOOKING_ALREADY_CANCELLED`, `EDIT_CLOSED`, `PARTY_TOO_LARGE`, `DAY_CHANGE_NOT_ALLOWED`, `SLOT_INVALID`, `DURATION_INVALID`, `ENDS_AFTER_CLOSING`, `TABLE_NOT_SUITABLE`, `SLOT_UNAVAILABLE` for a start ≤ now, then the locks, the re-check of status and cutoff, `SLOT_UNAVAILABLE` for a table overlap, `OVERLAPPING_BOOKING`, update and flush. As in create, an `IntegrityError` on the flush naming `ex_bookings_table_id_period` becomes `SLOT_UNAVAILABLE`, anything else is re-raised; PostgreSQL skips the row's own old version, so an edit over itself needs no extra code.
- No comments or docstrings in backend code, migrations or tests (Vlad's rule for this project).
- The first read of the booking is unlocked, only to learn the table; the booking row is locked last.
- Route `GET /api/v1/bookings/{booking_id}/slots?duration_minutes=` (required), answering `list[SlotResponse]`, no locks. Error order: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`, `BOOKING_ALREADY_CANCELLED`, `EDIT_CLOSED`, `DURATION_INVALID`.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.

## Implementation Notes

- `BookingSchedule` gained `is_free(start=, duration=, bookings=, now=)` (later than now, ends by closing, no overlap), used by search and the edit slots, plus `check_same_day`, `check_duration`, `check_ends_by_closing` and `check_editable`; the cancel and edit cutoffs share one private rule.
- `BookingService.edit` and `BookingService.list_edit_slots` share `_get_editable` (not found, cancelled, cutoff); edit calls it unlocked first and again after the user and table locks with `for_update=True`, which locks the booking row with `populate_existing`. The overlap queries take `excluding_booking_id`. Request schema `EditBookingRequest`.
- `populate_existing` was added to the locked `get_for_user`, so cancel's locked read uses it too; cancel reads the booking only once, so its behaviour does not change.
- Tests cover a 22:30 closing override on search, because the default settings never reach closing there.
- Verified by the implementer: ruff, format check, mypy, lint-imports (9 kept), pytest 415 passed. Format mismatches were fixed by hand, the formatter was not run. The live curl check is not done.
- Review patches (rows 17, 19-21, 23, 25): ADR 13 wording, `.env.example` comment, README.md / README.uk.md, two tests. Verified by the orchestrator: ruff, format check, mypy, lint-imports (9 kept), pytest 416 passed.
- Live check 2026-11-11 (server from this worktree on port 8001, local `app` at `0010`, no migration; user `edit-check@example.com` registered and verified through the API): Table 4 at 48 Rustaveli Avenue booked for 2026-11-12 12:00 (grid 11:00–13:00 taken); slots for 180 min list 10:00–20:00 with the booking itself free; edit to 180 min and party 4 answers 200 with 12:00–15:00 and the grid takes 13:30–14:30 too; with a second own booking at 16:00 on that table the 180-min slots skip 13:30–17:00; 13:30/180 409 `SLOT_UNAVAILABLE`; 21:00/150 400 `ENDS_AFTER_CLOSING`; 100 min 400 `DURATION_INVALID`; next day 400 `DAY_CHANGE_NOT_ALLOWED`; 12:15 400 `SLOT_INVALID`; party 5 400 `PARTY_TOO_LARGE`; unknown id 404; back to 90 min sent as `08:00Z` answers 12:00–13:30 `+04:00` and frees 13:30–14:30; moving onto an own booking at another table 409 `OVERLAPPING_BOOKING`; edit and slots of a cancelled booking 409 `BOOKING_ALREADY_CANCELLED`. All three bookings cancelled afterwards. No 5xx or traceback in the server log.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | Locked re-read keeps the stale identity-map object; edit could move a cancelled booking | high | `refresh_token_repository.py:18-21` solves the same case. Patched: Code Map, deferred-work task. |
| 2 | spec review | Exclusion `IntegrityError` on UPDATE not mapped | medium | `booking_service.py` maps it only around `add`. Patched: Design Notes, deferred-work task. |
| 3 | spec review | Closing can be broken through settings; create and search ignore it | medium | `test_settings.py:258-277` override ends at 24:00. Patched: closing enforced by edit and every grid; validator rejected again (book-a-table #10). |
| 4 | spec review | Shared availability rule has no owner | medium | `_is_free` private with fixed duration. Patched: `BookingSchedule.is_free`, slots on `BookingService`. |
| 5 | spec review | Offset test cannot catch a wrong day comparison | medium | Tbilisi grid maps to the same UTC date. Patched: local-day rule and two tests. |
| 6 | spec review | `add_booking` duration, sign-in parametrize, tag description, boundary rows | low | `test_bookings.py:157-176`, `:659`, `openapi_tags.py`. Patched. |
| 7 | spec review | Slots row omits morning starts; Move row lacks required fields | low | Patched rows. |
| 8 | spec review | Slots ignore the user's other bookings | low | Decided: same as search; edit refuses with `OVERLAPPING_BOOKING`. Recorded in Always. |
| 9 | edge | Create does not check closing when `closing_time < last_slot + duration` | low | Settings-only; the frozen Always rule keeps create unchanged and adds no validator. Rejected. |
| 10 | edge | `max_duration_minutes` below `duration_minutes` or off-step gives an empty set | low | Misconfiguration only; no validator by decision (book-a-table #10). Rejected. |
| 11 | edge | Closing after midnight makes every start unavailable | low | Misconfiguration only. Rejected; the same-day rule is documented in `.env.example` (#20). |
| 12 | edge | Table capacity may change between the unlocked and the locked read | false | Tables are written only by migrations (book-a-table #23). |
| 13 | edge | Empty grid (`first_slot > last_slot`) raises `IndexError` in slots | low | Misconfiguration only; search indexes `starts[0]` the same way. Rejected. |
| 14 | edge | `starts_at` near `datetime.min/max` overflows to 500 | low | Crafted input only; rejected for create too (book-a-table #25). |
| 15 | edge, blind | Edit checks only `party_size <= capacity`, create also `capacity <= max_online_party_size` | low | Needs the limit lowered below existing tables' capacity; the frozen Always rule names only the capacity. Rejected. |
| 16 | blind | Live curl check not done | false | Not a code defect; it is the step 5 check on the local server. |
| 17 | blind | ADR 13 states "every stay ends by closing" as an invariant although create relies on the defaults | low | ADR amendment text. Patch: say edit and the grids enforce closing, create holds it only through the defaults. |
| 18 | blind | Durations are not discoverable through the API | low | backend.md: descriptions name limits without numbers; no settings route asked (book-a-table #30). Rejected. |
| 19 | blind | Cutoff test's 200 branch asserts only the status | low | `test_edit_closes_at_the_cancel_cutoff`. Patch: assert the stored 14:00–16:00 stay. |
| 20 | blind | Closing is bound to the start's calendar day without a word | low | `_ends_by_closing` uses `to_local(start).date()`. Patch: the `.env.example` comment says the same local day. |
| 21 | blind | Start ≤ now refusal checked only inside the error-order test, without the unchanged row | low | Patch: own case with `stored_period` unchanged. |
| 22 | blind | No test for slots without `duration_minutes` | low | backend.md "API checks": trivial missing-field cases are not covered. Rejected. |
| 23 | blind | ADR 13 does not record that slots ignore the user's other bookings | low | workflow.md rule 5. Patch: one sentence in the Editing item. |
| 24 | blind | `BookingSchedule` imports the `Booking` model for a type | false | ADR 11 lets services import models; no caller diverges. |
| 25 | blind | README feature line does not mention editing | low | `README.md:31`. Patch: README.md and README.uk.md. |
| 26 | verification-gap | Day comparison never tested where the local and UTC dates differ | low | Pre-verified, but in `Asia/Tbilisi` every grid start (06:00–17:30Z) has the same UTC and local date, so the regression cannot reach users. Vlad (2026-11-11): the restaurant always runs in Georgian time. Rejected. |

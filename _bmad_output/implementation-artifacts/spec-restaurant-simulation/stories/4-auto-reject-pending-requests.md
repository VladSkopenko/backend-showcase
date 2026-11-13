---
title: 'Auto-reject requests 2 hours before start'
type: 'feature'
created: '2026-11-13'
status: 'done'
baseline_commit: '29d590b29278180b8221ad7967ece166ee695f45'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/2-staff-role-and-request-decisions.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/3-request-decision-notifications.md'
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/docs/adr/0018-in-app-notifications.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A large-party request nobody answers stays `PENDING` until and after its start: the guest never learns the outcome and keeps the time blocked.

**Approach:** A periodic task inside the API process rejects every request still pending once its start is 2 hours away or less, and notifies its participants exactly like a staff rejection (notification rows and emails). Staff can no longer approve such a request.

## Boundaries & Constraints

**Always:**
- Settings `booking.auto_reject_lead_minutes` (default 120) and `booking.auto_reject_interval_seconds` (default 60).
- The sweep: one transaction per run; select `PENDING` requests with `starts_at - lead <= now`, lock them `FOR UPDATE SKIP LOCKED`, lock the recipients' user rows `FOR KEY SHARE` first (ADR 13 order: users, then bookings), set `REJECTED`, `decided_at = now`, `decided_by_id = NULL` (NULL marks an automatic decision for the staff dashboard), write `BOOKING_REQUEST_REJECTED` notifications in the same transaction, send the emails after the commit with the same skip rules. A run that fails is logged, rolled back, and the next run tries again; it never stops the loop.
- The task starts with the app's lifespan and stops cleanly on shutdown; one API process per environment runs it (SPEC). It opens its own session, as ADR 11 requires for background work.
- Approve refuses a request inside the lead window with 409 `REQUEST_EXPIRED` (same code as a passed start), so staff and the sweep never race on it. Reject stays allowed.
- Notice building for decisions (recipients, local time, location, party size) and the email sender factory become reusable without HTTP: one place builds notices for both staff decisions and the sweep; the sender factory moves out of `auth/endpoints` into `app.infrastructure.email`.
- The rejection email and notification are the same as a staff rejection.

**Never:** A separate worker process, Redis or a scheduler library; auto-approval; reminders; changing the 2-hour rule per location.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sweep rejects | pending request starting in 90 min, owner and joined user | `REJECTED`, `decided_by_id` NULL, `decided_at` set; both get `BOOKING_REQUEST_REJECTED`; emails per skip rules | N/A |
| Sweep leaves | pending request starting in 3 hours; confirmed booking starting in 1 hour | unchanged | N/A |
| Boundary | start exactly `lead` away | rejected | N/A |
| Locked row | request locked by a concurrent staff decision | skipped this run, handled by the next if still pending | N/A |
| Failing run | the database errors mid-run | rolled back, logged; next run works | error logged |
| Late approve | staff approve a request starting in 90 min | unchanged | 409 `REQUEST_EXPIRED` |
| Owner after sweep | cancel or edit | unchanged | 409 `BOOKING_REJECTED` |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/bookings/services/booking_request_service.py` -- `_notices` (story 3) moves into a reusable notice builder used by approve, reject and the sweep; approve's expiry check uses the lead window.
- `backend/src/app/features/core/bookings/services/` -- new `RequestExpiryService` (sweep in one session: select, lock recipients, lock requests, reject, notify) returning the notices for emailing.
- `backend/src/app/features/core/bookings/repositories/booking_repository.py` -- expired-pending selection with `SKIP LOCKED`; reuse `BookingParticipantRepository.lock_account_holders` (story 3).
- `backend/src/app/features/core/notifications/services/booking_decision_notifier.py`, `decision_email_service.py` -- reused unchanged.
- `backend/src/app/features/core/auth/endpoints/dependencies.py:36` -- `get_email_sender` logic moves to `app.infrastructure.email` (a plain factory from settings); the dependency calls it.
- `backend/src/app/infrastructure/background_tasks/` -- new: the periodic runner (asyncio loop with interval, own session via `app.common.database.get_sessionmaker`, error logging). Creating it means dropping `.**` for it in the import contracts (`backend/pyproject.toml`, ADR 11 l.85-87).
- `backend/src/app/main.py:53` -- `create_app` gets a lifespan that starts and cancels the runner.
- `backend/src/app/config/settings.py` -- the two booking settings; `.env.example`.
- Tests: the sweep service is tested directly with `fake_clock` and `session_factory`; the runner loop with a short interval and a fake sweep; approve's window in `tests/test_booking_request_decisions.py`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_request_expiry.py` -- new; one test per matrix row, first and failing -- contract.
- [x] `backend/tests/test_settings.py`, `tests/test_booking_request_decisions.py` -- settings pins, late approve -- pins.
- [x] Notice builder extraction, `RequestExpiryService`, repository query, approve window -- behaviour.
- [x] Email sender factory in `app.infrastructure.email`; runner in `app.infrastructure.background_tasks`; lifespan in `main.py`; import contracts -- wiring.
- [x] `docs/adr/0013-...` and `0018-...` -- amend: lead window, automatic decisions with NULL `decided_by_id`, the in-process runner -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and `lint-imports` passes with the new contracts.
- Given the local API running, when a pending request's start comes within the lead window (use a request a little over 2 hours ahead and wait, or a lowered lead setting), then within one interval it is `REJECTED` and its owner has the notification.

## Implementation Notes

- 2026-11-13: implemented by a subagent from this spec; 625 tests, ruff, format check, mypy, 10 import contracts clean.
- Notices: `services/decision_notice_builder.py` (`DecisionNoticeBuilder.build(kind=, booking_ids=)`), built inside `BookingRequestService` and `RequestExpiryService` from the session, like `BookingSchedule`.
- Window: `BookingSchedule.check_approvable` raises `REQUEST_EXPIRED` when `starts_at <= now + lead`; `auto_reject_starts_by` gives the same cutoff to the sweep. The error message now says the request starts too soon or has started; the approve description names the lead without its number.
- Sweep: `RequestExpiryService.reject_expired` reads the expiring ids, key-share locks their account holders, then one `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED) RETURNING id` sets `REJECTED`, `decided_at`, `decided_by_id = NULL`; notices are built and recorded for the returned ids only. Requests whose start already passed are swept too.
- Runner: `app.infrastructure.background_tasks` holds `PeriodicTask` (generic loop: run, log any `Exception`, sleep; `stop()` cancels) and `RequestExpiryJob` (own session from the injected sessionmaker, commit or roll back, then `DecisionEmailService.send` after the commit). `main.py` gets a `lifespan` that builds the job with `get_sessionmaker()` and `create_email_sender(...)` and starts/stops the task named "request expiry". The first run happens at startup, then every interval.
- `create_email_sender(settings=, environment=)` lives in `app/infrastructure/email/email_sender_factory.py`; `get_email_sender` calls it.
- Contracts: `.**` dropped for `app.infrastructure.background_tasks` in both contracts; forbidden and protected contracts treat modules as packages by default, so descendants stay covered.
- Tests: the locked-row test commits its own location, table, user and request on a separate engine connection (SKIP LOCKED needs a second transaction that sees the row) and deletes them in `finally`; it does not use `no_locations`. The failing-run test drives the real job through `PeriodicTask`. Late approve is pinned in both test files (boundary 90/120/121 minutes in `test_booking_request_decisions.py`), plus reject inside the lead.
- Live check, local API on `app` at 0019 with `BOOKING_AUTO_REJECT_LEAD_MINUTES=2880` and `BOOKING_AUTO_REJECT_INTERVAL_SECONDS=15`: registered `auto-reject-check@example.com` (local debug code), requested Table 8 for 6 at 2026-11-14 19:00; 15 s later it was `REJECTED` with `decided_by_id` NULL, the owner had one `BOOKING_REQUEST_REJECTED` notification, cancel answered `BOOKING_REJECTED`; SIGINT logged "Application shutdown complete". No email was logged because the address is on a skipped domain. Staff approve inside the lead was not checked live (the waiter bot's password is not known here); it is covered by tests.

- 2026-11-13, parent session: 635 tests, linters, 10 contracts. Live on the local API with email disabled: with the lead at 25 h a request for tomorrow 10:00 answered REQUEST_TOO_LATE; a request two days ahead was PENDING; after a restart with the lead at 48 h the sweep rejected it within 20 s with decided_by_id NULL, the owner got BOOKING_REQUEST_REJECTED and the rejection email was logged. The INFO line of a run did not appear in the uvicorn output because the app configures no logging level for its own loggers (only WARNING and above show).

## Spec Change Log

- Vlad, 2026-11-13: requests inside the lead are refused at create (409 `REQUEST_TOO_LATE`). After review the staff list also shows only requests starting beyond the lead, the two settings are bounded (`lead >= 0`, `interval > 0`), a run that rejects requests logs one INFO line with the count, and the lifespan uses the app's settings and disposes the engine on shutdown.

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Requests can be created inside the lead (edge-case, blind) | medium | create only refused a passed start; the sweep then rejected the request within a minute. | patch: REQUEST_TOO_LATE at create (Vlad's default) |
| Staff list and approve use different windows (blind) | low | list filtered on now, approve on now + lead. | patch |
| Settings accept 0 or negative values (edge-case, blind) | low | no Field bounds. | patch |
| Successful runs log nothing (blind) | low | only failures logged. | patch: INFO line with the count |
| Lifespan ignores app settings and never disposes the engine (blind) | low | read get_settings() directly. | patch |
| Past-start sweep, multi-request run, accountless guest untested; duplicate test (verification-gap, blind) | low | all sweep tests started in the future. | patch |
| ADR 13 old bullet contradicts the window; NULL decided_by_id ambiguous; first-run backlog (acceptance, blind, verification-gap) | low | text. | patch: ADR 13 aligned, consequences added |
| Unbounded sweep batch (edge-case) | low | dev volume is small. | rejected |
| Duplicated transaction handling in the job (blind) | low | refactor only. | rejected |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

**Manual checks (if no CLI):**
- Live run on the local API with `BOOKING_AUTO_REJECT_LEAD_MINUTES` raised so a fresh request falls in the window.

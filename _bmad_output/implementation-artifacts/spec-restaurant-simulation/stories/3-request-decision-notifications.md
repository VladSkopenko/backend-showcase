---
title: 'In-app notifications and decision emails'
type: 'feature'
created: '2026-11-13'
status: 'done'
baseline_commit: 'd8889ff153460ec8ae7442de770939a143b37a61'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/2-staff-role-and-request-decisions.md'
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** When staff approve or reject a large-party request (story 2), nobody tells the guest; they only see it if they reopen their bookings.

**Approach:** Every decision creates an in-app notification for each signed-up participant of the request, in the same transaction as the decision, and sends them an email after the commit. Users list their notifications and mark them read.

## Boundaries & Constraints

**Always:**
- New core feature `notifications` (model, repository, service, endpoints, templates). Bookings imports it one way (ADR 11); it imports nothing from bookings.
- A notification: id, user, kind (`BOOKING_REQUEST_APPROVED`, `BOOKING_REQUEST_REJECTED`), booking, created at, read at. Recipients: the owner and every participant with an account; guests without an account get none (they see the status on their booking).
- Approve notifies the approved request's participants (approved) and the participants of every request it rejected (rejected); reject notifies its request's participants (rejected). The bulk reject returns the ids it changed. The notification rows are written in the decision's transaction, so a decision never commits without them.
- Emails go after the commit through FastAPI `BackgroundTasks`, as auth does: one email per recipient with the kind, date and time, location, party size and a link to the booking on the frontend (`frontend_url`). Addresses whose domain is in `notifications.skip_email_domains` (setting, default `["example.com"]`) get no email. Sending never raises: failures are logged and the decision stands; with email unconfigured the existing logging sender applies.
- `GET /notifications`: the signed-in user's own, newest first, `unread_only` filter, page envelope (`items`, `total`, `limit` 20 by default and at most 50, `offset`). `POST /notifications/{id}/read` sets `read_at` once and answers the notification; a second call keeps the first time; another user's or an unknown id answers 404 `NOTIFICATION_NOT_FOUND`. OpenAPI tag `Notifications`, after `Staff`.
- The auto-reject of story 4 must be able to reuse the same notifier without HTTP.

**Never:** Push or WebSocket delivery, notifications for anything but request decisions, notifications for guests without an account, unsubscribe settings.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Approve | request with owner and a joined user, plus a competing request | owner and joined user: `BOOKING_REQUEST_APPROVED`; competitor's owner: `BOOKING_REQUEST_REJECTED`; one email each | N/A |
| Reject | request with owner and an account-less guest | owner: `BOOKING_REQUEST_REJECTED` and an email; guest nothing | N/A |
| Skipped domain | owner `...@example.com` | notification stored, no email sent | N/A |
| Email fails | sender raises | decision and notifications committed | error logged |
| Failed decision | approve answers `SLOT_UNAVAILABLE` | no notifications, no emails | N/A |
| List | user with read and unread notifications | own only, newest first; `unread_only=true` filters | N/A |
| Mark read | own unread notification, twice | `read_at` set by the first call, unchanged by the second | N/A |
| Foreign | another user's notification id | unchanged | 404 `NOTIFICATION_NOT_FOUND` |
| Anonymous | list or mark read without a session | nothing | 401 `NOT_AUTHENTICATED` |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/notifications/` -- new: `models/notification.py`, `enums/notification_kind.py`, `repositories/`, `services/` (notifier writing rows; email service rendering and sending, never raising), `dto/`, `schemas/`, `endpoints/` (routes, `errors.py`, `openapi_tags.py`, `dependencies.py`), `templates/` (Jinja2 html and txt, layout like `features/core/auth/templates/email_layout.html`).
- `backend/src/app/features/core/auth/services/verification_email_renderer.py`, `verification_email_service.py` -- the pattern for rendering and for a send that logs instead of raising; `auth/endpoints/dependencies.py:36` `get_email_sender` and `EmailSenderDep` (:54) give the sender.
- `backend/src/app/features/core/auth/endpoints/auth.py:84` -- the `BackgroundTasks.add_task` pattern after a committed request.
- `backend/src/app/features/core/bookings/services/booking_request_service.py` -- approve (:58) and reject (:89) call the notifier and return what the email step needs alongside the view.
- `backend/src/app/features/core/bookings/repositories/booking_repository.py:183` -- `reject_pending_overlapping` returns the rejected ids (`RETURNING`).
- `backend/src/app/features/core/bookings/endpoints/booking_requests.py` (:68, :92) -- schedule the emails with `BackgroundTasks`.
- `backend/src/app/config/settings.py` -- `NotificationSettings` (`skip_email_domains`), `app.frontend_url` (:23) reused for links.
- `backend/src/app/model_registry.py`, `backend/src/app/main.py` -- register the model, the router and the tag.
- `backend/migrations/versions/0019_create_notifications.py` -- new table and enum; downgrade drops both.
- Tests: fake senders are per module (`tests/test_registration.py:40`, overridden at :93 via `get_email_sender`); staff fixture and request helpers in `tests/support/`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_notifications.py` -- new; one test per matrix row, first and failing -- contract.
- [x] `backend/tests/test_database.py`, `tests/test_openapi.py`, `tests/test_settings.py` -- table shape, `Notifications` flow, the new setting -- pins.
- [x] `backend/migrations/versions/0019_create_notifications.py` -- schema.
- [x] Notifications feature, settings, model registry -- behaviour.
- [x] Booking request service, repository, staff endpoints -- wiring.
- [x] `docs/adr/` -- new ADR "In-app notifications": core feature, same-transaction rows, emails after commit, skipped domains -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass; CI's migration round trip succeeds.
- Given the local API at 0019, when the waiter bot approves one of two competing requests, then both owners see one notification each with the right kind and the logging sender (or SMTP) shows one email per non-skipped address.

## Implementation Notes

- Notifications feature: `BookingDecisionNotifier` (rows, takes only a session, reusable by story 4), `NotificationService` (list, mark read), `DecisionEmailRenderer` + `DecisionEmailService` (send per recipient, skip domains, log and never raise). DTOs `DecisionNotice` and `NoticeRecipient` carry what bookings knows; notifications imports nothing from bookings.
- Bookings: `BookingRequestService` takes the notifier, builds the notices from `BookingParticipantRepository.list_account_holders` and `BookingRepository.list_with_tables`, records them before returning `DecisionOutcome(view, notices)`; `reject_pending_overlapping` returns the ids via `RETURNING`. Staff routes schedule `DecisionEmailService.send` with `BackgroundTasks`.
- Email link is `{frontend_url}/reservations`, the frontend's "My Reservations" page; it has no page for one booking. Subjects: "Your booking request is approved" / "is rejected". Times in the email and in the notification API are in the restaurant time zone (`booking.timezone`), like the booking routes.
- Notification `created_at` is the decision's `decided_at`, passed to the notifier by the caller; list order is `created_at DESC, id DESC`, served by `ix_notifications_user_id_created_at_id`; `booking_id` has its own index.
- Lock order (ADR 13 amended): before the table lock, approve reads the overlapping pending requests and key-share locks (`FOR KEY SHARE`, id order) the user rows of the account-holding participants of the request and those competitors; reject does the same for its request before locking it. The notification FK checks would otherwise take those locks after the table and booking locks and could deadlock with create or edit, which lock the user `FOR UPDATE` first.
- Skip-list entries are normalised (`strip`, leading `@`, lower case); exact domain match, no subdomains. Import-linter contract "Notifications import nothing from bookings" added.
- `NOTIFICATIONS_SKIP_EMAIL_DOMAINS` (JSON list) added to `.env.example`; `tests/conftest.py` clears `NOTIFICATIONS_` variables. ADR 18 added and listed in both READMEs.
- Verified before the review fixes: 607 tests; ruff, format check, mypy, lint-imports clean; round trip on a throwaway Postgres 18 (`upgrade head`, `downgrade base`, `upgrade head`, `alembic check`). After the review fixes only the notification, decision, database and OpenAPI test modules and the static checks were re-run; the round trip was not re-run with the composite index. Live curl on the local API is pending Vlad migrating `app` to 0019.

- 2026-11-13, parent session: 612 tests, linters, 10 import contracts; round trip and `alembic check` on a throwaway Postgres. Live check on the local API at 0019 with email sending disabled (logging sender): the waiter bot approved one of two competing requests; the approved owner (familyrest-check.dev) got BOOKING_REQUEST_APPROVED and one logged email 'Your booking request is approved'; the rejected owner (example.com) got BOOKING_REQUEST_REJECTED and no email; mark read twice kept the first time; a foreign id answered NOTIFICATION_NOT_FOUND; anonymous NOT_AUTHENTICATED. Local check users: notify-check@familyrest-check.dev.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Notification FK key-share on users after table lock can deadlock with create/edit (edge-case) | medium | create/edit lock user FOR UPDATE then table; the decision held table and request first. | patch: recipients locked FOR KEY SHARE first |
| created_at from a second clock call (acceptance) | low | notifier called clock.now() itself. | patch |
| Email link to a missing frontend page (blind) | medium | family-rest has /reservations only. | patch |
| Skip domains not normalised (edge-case, blind) | low | raw comparison. | patch |
| Rejection footer wrong for joined users and cascades (blind) | low | text addressed the owner only. | patch |
| List index does not cover the order (blind) | low | single-column user_id index. | patch: composite index |
| Import direction not enforced (blind) | low | no contract. | patch: forbidden contract |
| Descriptions promise an email to everyone (blind) | low | skipped domains get none. | patch |
| ADR 18 silent on growth and the auth dependency (blind) | low | text. | patch |
| Multi-competitor, mixed-domain, partial-failure, HTML-escape cases untested (verification-gap, blind) | low | single-recipient tests only. | patch: tests added |
| Story 4 cannot reuse notice building (acceptance, blind) | low | `_notices` is private. | rejected: story 4 extracts it |
| Repeated location reads under locks, empty IN (blind) | low | small N. | rejected |
| List items carry no booking details (blind) | low | frontend not wired yet. | rejected, revisit with the frontend |
| Live check pending (acceptance) | low | done: see Implementation Notes. | resolved |
| Late joiner between the unlocked read and the user lock; staff row key-share after table lock (implementer) | low | narrow windows left after the fix. | defer |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

**Manual checks (if no CLI):**
- Migration round trip on a throwaway Postgres; live curl on the local API after Vlad migrates `app` to 0019.

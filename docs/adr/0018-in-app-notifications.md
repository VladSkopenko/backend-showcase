# 18. In-app notifications

Date: 2026-11-13

## Status

Accepted. Amended 2026-11-13: the automatic rejection of stale requests (ADR 13) notifies like a
staff rejection; notices are built in one place and the email sender is built without HTTP.

## Context

Staff approve or reject large-party booking requests (ADR 13). Until now nobody told the guest:
they saw the decision only by reopening their bookings. An approval also rejects every competing
pending request on the same table and time, so one decision can concern several groups of people.
Push delivery and WebSocket come later with the order tracker; the first channel is a list the
user reads in the app, plus an email.

## Decision

- **A core feature that knows nothing about bookings.** `features/core/notifications` owns the
  table `notifications`: user (CASCADE), kind (`BOOKING_REQUEST_APPROVED`,
  `BOOKING_REQUEST_REJECTED`), booking (CASCADE), created at and read at. It references
  `bookings.id` only by a foreign key and imports nothing from bookings. Bookings imports it one
  way (ADR 11): it decides who is told what and hands the notifications feature plain
  `DecisionNotice` dataclasses (kind, booking, local start, location, party size, recipients).
- **Recipients are participants with an account.** The owner and every joined user of the decided
  request get one notification each; guests without an account get none and see the status on
  their booking. An approval also notifies the participants of every request it rejected; the
  bulk reject returns the ids it changed (`RETURNING`).
- **Rows in the decision's transaction.** `BookingDecisionNotifier` writes the rows on the
  request's session before the commit, stamped with the decision's `decided_at`, so a decision
  never commits without its notifications and a failed decision leaves none. The row inserts
  key-share lock the recipients' user rows through the foreign key, so a decision locks those
  rows first, in id order, to keep the ADR 13 order user, table, booking. The notifier takes only a session, so the automatic rejection of
  stale requests can call it without HTTP.
- **Automatic rejections notify like staff rejections.** The periodic task that rejects requests
  still pending inside the auto-reject lead (ADR 13) writes `BOOKING_REQUEST_REJECTED` rows in
  its own transaction and sends the same emails after its commit, with the same skipped domains.
  `DecisionNoticeBuilder` in bookings builds the notices (recipients, local start, location,
  party size) for staff decisions and the task alike. Without a request there are no
  `BackgroundTasks`: the task awaits `DecisionEmailService.send` itself after the commit, and
  builds its sender with `create_email_sender` from `app.infrastructure.email`, the same factory
  the request dependency uses.
- **Emails after the commit, never failing the decision.** The staff routes schedule
  `DecisionEmailService.send` with FastAPI `BackgroundTasks`, as registration does. It sends one
  email per recipient through the existing `EmailSender` (SMTP, or the logging sender when email is
  not configured), logs any failure and never raises. The email names the decision, date and time,
  location and party size, and links to the user's reservations at `{frontend_url}/reservations`
  (the frontend has no page for one booking).
- **Skipped domains.** Addresses whose domain is in `notifications.skip_email_domains` (default
  `example.com`, where the bots and test accounts live) get no email; their in-app notifications
  are still stored. Entries match the domain exactly, ignoring case, spaces and a leading `@`;
  subdomains are not covered.
- **Read once.** `GET /notifications` lists the caller's own, newest first, optionally unread only,
  in the usual page envelope. `POST /notifications/{id}/read` sets `read_at` the first time and
  keeps it afterwards; another user's id answers `NOTIFICATION_NOT_FOUND`, the same as an unknown
  one.

## Alternatives considered

- **Sending emails inside the transaction.** Simpler, but a slow or failing SMTP server would hold
  the booking locks or fail a decision that is already correct.
- **An outbox table with a worker.** Guarantees delivery across restarts, but the project has no
  worker yet and an email lost on a restart is acceptable: the in-app notification stays.
- **Deriving notifications from bookings at read time.** No new table, but there is no read state
  to keep and the list would have to know every kind of event that may later notify a user.

## Consequences

- Every new decision path (the automatic rejection included) must record notices through the
  notifier in its own transaction and send the emails only after that transaction commits.
- An email lost between the commit and the send is not retried.
- Rows accumulate: there is no cleanup yet, and the simulator bots on dev get a row for every
  decision on their requests.
- Notifications depend on core auth for `RenderedEmail` and for the email sender dependency; the
  sender itself comes from `app.infrastructure.email`.
- The rule that notifications import nothing from bookings is an import-linter contract.

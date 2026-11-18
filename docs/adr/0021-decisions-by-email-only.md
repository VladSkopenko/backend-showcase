# 21. Decisions reach guests by email only

Date: 2026-11-18

## Status

Accepted. Supersedes [ADR 18](0018-in-app-notifications.md).

## Context

[ADR 18](0018-in-app-notifications.md) told guests about staff decisions on large-party requests
in two ways: a row in a `notifications` table, listed and marked read through
`GET /notifications` and `POST /notifications/{id}/read`, and an email. The final scope stops at
the pre-order, and the frontend has no screen for a notification list and will not get one. The
email already links to the reservations page, and the booking card there shows the request's
status. The rows also cost the decisions a lock: their foreign key key-share locks every
recipient's user row, so approve, reject and the automatic rejection had to lock those rows
first to keep the order of [ADR 13](0013-table-booking-slots-and-double-booking.md).

## Decision

- **Email is the only channel.** Staff approvals and rejections, the rejections an approval
  causes and the automatic rejection of stale requests send the same decision emails as before:
  one per participant with an account, after the commit, never failing the decision, with the
  skipped domains of `notifications.skip_email_domains`. Guests without an account see the status
  on their booking.
- **The in-app list goes.** The two notification routes, the `Notification` model, its
  repository, schemas, service and errors are removed. Migration `0025` drops the table
  `notifications` and the enum `notification_kind`; its downgrade recreates both as `0019` did.
- **No recipient locks.** Decisions no longer key-share lock the participants' user rows before
  the table and the request.
- **The package stays as the email home.** `features/core/notifications` keeps `DecisionNotice`,
  `NoticeRecipient`, the `NotificationKind` enum, `DecisionEmailService`, its renderer and the
  templates; the `NOTIFICATIONS_` settings prefix and the template loader depend on its name.
  Bookings still builds the notices and imports the package one way.

## Alternatives considered

- **Keep the list for a later screen.** Code, a table and a lock in every decision for a screen
  nobody builds.
- **Realtime delivery (WebSocket or push).** The guest learns the outcome from the email and the
  booking card already; a live channel is not worth its infrastructure for this scope.

## Consequences

- Migration `0025` deletes the existing notification rows on every environment; its downgrade
  recreates an empty table, so the rows do not come back.

- A guest whose address is on a skipped domain learns about a decision only from the booking
  card.
- An email lost between the commit and the send is not retried, and nothing else records the
  decision for the guest besides the booking's status.
- Approve, reject and the automatic rejection lock only the table and the requests; the
  `decided_by_id` write key-share locks the staff user row after them, a known exception recorded
  in ADR 13.

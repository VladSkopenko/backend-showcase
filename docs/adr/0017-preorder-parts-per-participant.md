# 17. Pre-order parts per participant

Date: 2026-11-11

## Status

Accepted

## Context

The Figma Guest Flow lets every person at a booking pick dishes for the visit: a menu with the
reservation strip, a dish card with "Pre-Order", a cart drawer with steppers and "Submit
Pre-Order", and "Pre-Order Submitted" with "Create New Pre-Order". The owner has the same "Add
Pre-Order". Participants (ADR 16) already say who belongs to a booking, as a signed-in user or a
guest known by the `guest_token` cookie. Later pull requests let the owner see the whole group,
remove a guest with their items and send the group to the restaurant.

## Decision

- **A regular feature with one draft per participant.** `features/preorder` owns the table
  `preorder_items`. Each line belongs to a participant (`participant_id`, CASCADE), never to a
  booking directly: the booking comes through the participant. Every participant, the owner
  included, keeps their own draft on the server, so it survives reloads and sign-outs. A draft
  holds one line per dish with a quantity and one note; a partial unique index on
  `(participant_id, dish_id) WHERE state = 'DRAFT'` backs that rule. Pre-order imports only core
  features (ADR 11): it asks core bookings who the caller is and core menu for the dishes.
- **Submit moves the draft into one part of the group.** Submit turns every draft line into
  `SUBMITTED` with one new `submission_id` and one `submitted_at`, and leaves an empty draft. A
  submitted part is final for its author: there is no edit or withdrawal. A participant can submit
  several parts; each reads back on its own, oldest first. Guests see only their own items.
- **Live prices until the restaurant send.** Lines store no price. Carts and parts show the
  menu's current `price_cents`, availability and `prep_minutes` at read time. The price is fixed
  when the owner sends the group to the restaurant, in a later pull request. A dish that becomes
  unavailable stays in the draft; it can be lowered, noted or removed, but not added, raised or
  submitted.
- **One window, shared with join.** `BookingSchedule.preorder_open` holds the rule: pre-order is
  open while `starts_at - now >= preorder_lock_minutes`, the same boundary as join (ADR 16), so
  exactly that many minutes before the start is still open. Core bookings answers the caller's
  participant id and whether pre-order is open (confirmed and inside the window); pre-order raises
  its own `PREORDER_CLOSED`. Reads stay open after the window and after a cancel.
- **Every pre-order write takes the booking row lock.** Set, remove and submit lock the booking
  row (`FOR UPDATE OF bookings`, re-read with `populate_existing`) in the query that finds the
  caller's participant, with no join to `dining_tables`. The lock alone serialises a double submit
  (the second answers `CART_EMPTY`) and a write racing the owner's cancel (the write sees the
  cancel and answers `PREORDER_CLOSED`); no constraint backs either. It also serialises two writes
  of one dish, where the partial unique index is the backstop. Pre-order writes lock no users or
  tables, so they add no cycle to the ADR 13 order (user, table, booking) or the join order (user,
  booking). Line inserts take `FOR KEY SHARE` on the dish and participant rows; nothing locks those
  `FOR UPDATE` today.
- **Removing a guest locks the booking first.** The participant CASCADE deletes a removed guest's
  pre-order with them ("remove Alex and his pre-order"). The remove-guest path in the next pull
  request must lock the booking row before deleting the participant, so it serialises with the
  guest's own pre-order writes.

## Alternatives considered

- **One shared cart per booking.** Fewer rows, but every participant would edit everyone's lines,
  and the Figma flow shows each person their own cart.
- **A price snapshot on every line.** Exact history from the first click, but the price the
  restaurant charges is fixed only when the owner sends the group; earlier snapshots would need
  re-pricing anyway.
- **A separate `pre_order_submissions` table.** A natural home for a part's status later, but
  today a part has only an id and a time, both carried by its lines.
- **Locking the participant row instead of the booking.** Narrower, but the cancel and the window
  live on the booking, and the owner's group actions need one lock for the whole booking.

## Consequences

- Every write path that changes participants or pre-order lines of a booking must take the
  booking row lock first.
- `dish_id` is RESTRICT: a dish with pre-order lines cannot be deleted; the menu marks dishes
  unavailable instead.
- The booking locks and the double submit need two concurrent connections to test; the
  shared-connection test harness cannot observe them.

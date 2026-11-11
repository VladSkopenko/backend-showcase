# 15. Booking participants and guest identity

Date: 2026-11-11

## Status

Accepted

## Context

The Figma flows let the owner of a booking share an invite link (`/join/<code>`) and let friends
join the reservation, with or without an account ("You're Invited!", "Enter Your Name"). Group
pre-order in the next pull requests needs to know who belongs to a booking. Until now a booking had
only its owner in `bookings.user_id`, and every caller of the API was a signed-in user.

## Decision

- **Participants are part of the core bookings feature.** `booking_participants` holds one row per
  person in a booking, with role `OWNER` or `GUEST` and exactly one of `user_id` or `guest_id`
  (`CHECK (num_nonnulls(user_id, guest_id) = 1)`). Creating a booking adds the `OWNER` row; a
  partial unique index allows one `OWNER` per booking, and migration `0012` backfilled the owners
  of existing bookings. Owner checks keep using `bookings.user_id`, which always equals the owner
  participant's `user_id`. Every booking response carries the caller's `role` and the participants,
  shown by the user's first name or the guest's entered name. Cart, orders and reviews build on
  participants, so they belong to core rather than to a regular feature.
- **Invites are the first regular feature.** `features/invites` owns the code
  (`booking_invites`, one per booking, created on the first link request), the public preview and
  the join route. It maps a code to a booking and calls the participant service of core bookings
  for every rule, so the join rules stay in one place and invites imports only core features
  (ADR 11).
- **Guests without an account are known by a cookie with a hashed token.** Joining without an
  account creates a `guests` row with the entered name, the SHA-256 of a random 256-bit token and
  an expiry. The token goes to the httpOnly, Secure, SameSite=Lax cookie `guest_token`; only the
  hash is stored, as for refresh tokens. A guest with a valid cookie reuses the row on other
  bookings, keeps the name and gets the expiry and the cookie renewed. An unknown or expired
  cookie counts as no guest. When the access cookie and the guest cookie both arrive, the user
  wins. A guest is never merged into an account.
- **The seat rule holds under the booking lock.** Owner and guests never exceed `party_size`. Join
  locks the booking row (`FOR UPDATE`, re-read with `populate_existing`) before it counts the
  participants with a fresh query, so two joins for the last seat serialise; edit refuses a
  `party_size` below the participant count after taking its locks. Join closes when the booking is
  cancelled and at the pre-order lock (`preorder_lock_minutes` before the start).
- **Join lock order, an addition to ADR 13.** A signed-in joiner's user row is locked first, then
  the booking row. The participant insert takes `FOR KEY SHARE` on the user row, which conflicts
  with the `FOR UPDATE` that create and edit hold on users; locking the joiner first keeps the ADR
  13 order (user, table, booking) for every write path. The first link request locks the booking
  row too, so two first requests cannot both insert a code.

## Alternatives considered

- **Participants inside the invites feature.** Pre-order and later features would have to import a
  regular feature or move the table later; owner views would need invites to show participants.
- **An account required to join.** Simpler identity, but the Figma flow lets friends join with only
  a name.
- **The guest token stored in plain text, or a signed cookie without a row.** A plain token in the
  database works as a password if the table leaks; a signed cookie alone cannot carry the name to
  other participants or be tied to participant rows.
- **A seat counter on bookings.** Faster to read, but a second source of truth next to the
  participant rows; the count under the booking lock is exact and the rows are few.

## Consequences

- A guest who clears cookies or switches devices cannot get back to the booking and has to join
  again under a new identity, which takes another seat. Removing a guest and leaving a booking come
  with the group pre-order.
- The access cookie lives 15 minutes, so the client refreshes the session before joining;
  otherwise a signed-in user without an access cookie joins as a guest.
- The join locks and the first-link race need two concurrent connections to test; the
  shared-connection test harness cannot observe them.
- Every write path on bookings now also writes or counts participant rows, and a future path that
  inserts bookings directly must insert the owner participant too.

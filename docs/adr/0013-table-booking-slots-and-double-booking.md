# 13. Table booking: fixed slots and double-booking protection

Date: 2026-11-11

## Status

Accepted

## Context

Guests book a table from the Figma "Book a Table" flow: they pick a date, a party size, a table and
a start time from a grid of slots. Two guests must never hold the same table at the same time, and
one guest must not hold two tables at once. Requests for the same table can arrive in parallel, and
a check in Python alone cannot see a row another transaction is about to insert.

## Decision

- **Fixed slot grid.** Starts are every `slot_minutes` from `first_slot` to `last_slot`, the same
  at every location, and every booking lasts `duration_minutes`. The values live in
  `BookingSettings` (`BOOKING_` prefix). Every date and grid rule is evaluated in the restaurant
  time zone (`BOOKING_TIMEZONE`): "now", "today", the horizon and the grid. A `starts_at` sent with
  any offset is converted first, and every datetime leaves the API in the restaurant time zone.
- **Half-open ranges.** A booking occupies `[starts_at, ends_at)`, so a booking ending at 13:30
  and one starting at 13:30 do not overlap. The service and the database use the same rule.
- **Stored end.** `ends_at` is stored next to `starts_at` rather than derived from the duration
  setting. Changing the duration, or letting a guest choose it later, needs no schema change and
  never reinterprets existing bookings.
- **Rules in the service, constraint as a backstop.** Creating a booking locks the user row, then
  the table row (`SELECT ... FOR UPDATE`), always in that order, and only then checks for a
  `CONFIRMED` booking that overlaps on the table (`SLOT_UNAVAILABLE`) or for the user
  (`OVERLAPPING_BOOKING`). The locks serialise competing requests for one table or one user, so the
  check sees every committed booking it competes with.
- **Exclusion constraint.** `ex_bookings_table_id_period` is
  `EXCLUDE USING gist (table_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status = 'CONFIRMED')`.
  It needs the `btree_gist` extension for the `uuid` equality, which the migration creates. A
  write path that skips the service still cannot double-book a table. An `IntegrityError` naming
  the constraint is turned into `SLOT_UNAVAILABLE`.
- The user-level overlap rule (`OVERLAPPING_BOOKING`) is held only by the service under the user
  row lock. It has no database backstop.
- Cancelled bookings stay as rows with status `CANCELLED` and do not block their slot.

## Alternatives considered

- **A row per slot** (a pre-generated availability table). Simple uniqueness, but the table must
  be filled ahead for every table and day, and a change to the duration or the grid rewrites it.
- **Only the exclusion constraint.** Correct, but every conflict surfaces as a failed insert
  instead of a checked domain error. A second constraint,
  `EXCLUDE USING gist (user_id WITH =, tstzrange(starts_at, ends_at) WITH &&)`, could hold the
  user-level overlap too; it was not added.
- **Only the service check.** Without the locks two parallel requests both pass the check; without
  the constraint a future write path could skip the rule.
- **Serializable isolation.** Would also catch the race, but for the whole transaction and with
  retries the request flow does not have.

## Consequences

- `alembic check` cannot reflect exclusion constraints, so drift between the model and the
  database is caught only by the `pg_get_constraintdef` test in `tests/test_database.py`.
- The lock order (user, then table) is a rule for every future write path on bookings, such as
  editing a booking; taking the locks in another order risks deadlocks.
- Per-location or per-weekday opening hours would replace the single grid in `BookingSettings`.

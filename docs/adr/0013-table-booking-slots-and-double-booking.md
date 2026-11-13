# 13. Table booking: fixed slots and double-booking protection

Date: 2026-11-11

## Status

Accepted. Amended 2026-11-11: bookings can be edited (start, party size and a duration from a
fixed set) with the lock order user, table, booking; edit and the day grids enforce a closing
time. Amended 2026-11-13: parties above the instant limit send a pending request; the overlap
rules depend on the status, and one "active" rule names the statuses that hold a guest's time.

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
- **Large-party requests.** A party from `max_online_party_size + 1` up to
  `max_request_party_size` (8, bounded by the `party_size` CHECK) is stored with status `PENDING`
  on a table of capacity from the party size up to `max_request_party_size`; staff decide later.
  Instant bookings keep tables up to `max_online_party_size`, so tables above it are
  request-only and never compete with instant bookings (with the defaults, tables of 5 to 8
  seats). A request takes the same locks and the same date, slot and horizon checks as a
  booking.
- **Overlap per status.** The table checks, the exclusion constraint and the search and edit
  grids count only `CONFIRMED`: a pending request holds no table, several requests may compete
  for one table and time, and a request on a table with a confirmed overlap is refused with
  `SLOT_UNAVAILABLE`. The user check counts `CONFIRMED` and `PENDING` on create and edit, so a
  user cannot hold a booking and a request, or two requests, that overlap.
- **The active rule.** `BookingStatus.active()` (`CONFIRMED`, `PENDING`) replaces the checks for
  `CANCELLED` in cancel, edit, the invite link and joining. A later terminal status, such as a
  staff rejection, falls on the inactive side without changing those status checks. The error
  they report, `BOOKING_ALREADY_CANCELLED`, is cancellation-specific; story 2 generalises it
  together with `REJECTED`. A pending request can be cancelled and joined like a
  booking, cannot be edited (`BOOKING_PENDING`) and keeps the pre-order closed; edit keeps the
  instant party limit, so it never turns a booking into a request.
- **Editing.** The owner of a `CONFIRMED` booking may replace its start, party size and duration
  until the cancel cutoff. The table and the local day stay. Durations run from
  `duration_minutes` to `max_duration_minutes` in steps of `slot_minutes`; creation still uses
  `duration_minutes`. Edit locks the user row, then the table row, then the booking row, so it
  takes the create locks in the same order and never waits crosswise with create or cancel. The
  locked re-read of the booking uses `populate_existing`, and status and cutoff are checked again
  under the lock. The overlap checks skip the edited booking itself; the exclusion constraint skips
  the row's old version on `UPDATE`. Like search, the edit slots ignore the user's other
  bookings, so a start shown available can still be refused by edit with `OVERLAPPING_BOOKING`.
- **Closing time.** Edit and every day grid enforce `closing_time` on the start's local day: edit
  refuses a later end (`ENDS_AFTER_CLOSING`), and search and the edit slots mark such starts
  unavailable through one shared rule. Create does not check closing; it keeps it only through the
  defaults, where a standard stay from the last slot ends exactly at closing.

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
- The lock order (user, then table, then booking) is a rule for every write path on bookings;
  taking the locks in another order risks deadlocks.
- Per-location or per-weekday opening hours would replace the single grid in `BookingSettings`.

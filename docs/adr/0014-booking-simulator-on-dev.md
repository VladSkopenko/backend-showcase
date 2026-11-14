# 14. Booking simulator on dev

Date: 2026-11-11

## Status

Accepted. Amended 2026-11-13: migration `0018` adds a staff bot on dev and local with the same
bot password. Amended 2026-11-13: migration `0020` adds 36 named guest bots on dev, 40 booking
bots in all. Amended 2026-11-13: the simulator runs every 2 minutes on the platform n8n, plays
the 40 bots as regulars and occasional guests, sends large-party requests and pre-orders food.
Amended 2026-11-14: a second workflow, the waiter bot, decides large-party requests on dev.

## Context

Dev shows an empty booking grid, so nobody sees the booking flow
([ADR 13](0013-table-booking-slots-and-double-booking.md)) move. The roadmap plans n8n as a visitor
simulator that books random tables through the REST API, the same way a guest does. Bots need
verified accounts to sign in, and registration verifies an email with a code sent by mail; only
`local` echoes the code in the response. Staging and prod serve real guests, whose tables a bot
must never take. [ADR 7](0007-single-vm-platform-and-app-stacks.md) lets one n8n serve every
environment, with the environment as a workflow parameter; this record narrows the booking
simulator to dev.

## Decision

- **n8n is the visitor simulator, on dev only.** The workflow
  `n8n/workflows/booking-simulator.json` signs in as a bot and books, requests, pre-orders or
  cancels through the public dev API, every 2 minutes. It never runs against staging or prod.
- **Bots behave like guests.** Each run plays one of the 40 bots: bots 1 to 10 are regulars with
  a favourite location and two favourite dishes, bots 11 to 40 occasional guests, half of the runs
  each. When they book, how many come, how often they send large-party requests, pre-order and
  cancel follow weights in one `CONFIG` object at the top of the workflow, starting from the
  simulation patterns. Favourites come from a stable hash of the bot number or location id, so the
  workflow keeps no state. A confirmed booking more than 30 minutes ahead gets a pre-order, and
  so does an approved request that has none yet.
- **Large-party requests.** A party of 5 to 8 sends a request instead of booking, only for starts
  more than 2 hours ahead, which is as close as the API accepts one.
- **A waiter bot decides the requests.** A second workflow, `n8n/workflows/waiter-bot.json`, signs
  in as the staff bot every 5 minutes and approves or rejects pending requests through the staff
  routes of the public dev API, like a busy waiter: it skips some runs, leaves some requests far
  ahead for later, approves most and rejects the rest, by weights in its own `CONFIG` object. It
  reads one page of requests in the API's order and decides them one at a time, so the earliest
  of several competing requests is decided first. It keeps no state, never runs against staging
  or prod, and requests it leaves too long fall to the API's own 2-hour auto-reject.
- **Bots come from an environment-gated data migration.** Migration `0011` inserts four verified
  users, `booking-bot-1@example.com` to `booking-bot-4@example.com`, only when
  `APP_ENVIRONMENT` is `dev`; in every other environment its upgrade and downgrade do nothing. The
  migration runs in the normal deploy (`alembic upgrade head`), so the bots exist on dev without
  access to the server. Its downgrade deletes the four users, and their bookings go with them
  through the `ON DELETE CASCADE` on `bookings.user_id`. A plain insert: if one of the emails is
  already taken on dev, the migration fails loudly instead of adopting a foreign account.
- **Forty named booking bots.** Visitor statistics need distinct people, so migration `0020` adds
  `booking-bot-5@example.com` to `booking-bot-40@example.com` on dev only, under the same gate,
  password hash and plain insert as `0011`. Each has a distinct first and last name, a fixed mix of
  Georgian and international common names, not taken from any known person. Bots 1 to 4 keep
  their `Booking Bot N` names. No column marks a bot or its persona: the simulator decides which
  bots are regulars. The downgrade deletes exactly the 36 added emails, and their bookings,
  booking participations and notifications go with them through `ON DELETE CASCADE`.
- **A staff bot for staff decisions.** Migration `0018` inserts one verified staff user,
  `waiter-bot@example.com` (`is_staff` true), with the same password hash as the booking bots,
  when `APP_ENVIRONMENT` is `dev` or `local`; staging and prod never get it, and there its upgrade
  and downgrade do nothing. Local is included so the staff routes can be tried on a developer
  machine without flagging a user by hand; the test database, migrated as `local`, has it too.
  Its downgrade deletes the user, and a plain insert fails loudly on a taken email.
- **The password lives only in n8n.** The migration stores an Argon2id hash. The plaintext is kept
  by the owner and entered into the n8n Custom Auth credential `Booking bot password`, which n8n
  keeps encrypted in its own database. No file in the repository holds it. The hash itself is
  public, so the password is long and random (28 characters), out of reach of offline guessing.
- **Bots leave real guests a choice.** An instant booking goes only where at least 4 fitting
  tables are free at one location and one start time, so it never takes the last tables of a
  slot. A request holds no table, so the rule does not apply to it: one free fitting table is
  enough. When staff approve a bot's request, it may take the last big table for that start.
- **The platform n8n runs the workflow, imported from git.** It runs in the platform stack on the
  VM; the file in git is imported there through the editor. `n8n/compose.yml` runs n8n on the
  developer machine to try changes first.

## Alternatives considered

- **Register the bots through the API.** Verification needs the emailed code, which dev does not
  return, so it needs a mailbox per bot or a person reading codes.
- **A registration bypass or a bot flag on users.** Adds a code path or a column to the
  production schema only for a simulator, and a bypass is an attack surface on every environment.
- **Bots in every environment.** On staging and prod the bots would take tables from real guests
  and show up in their data.

## Consequences

- Migrations `0011` and `0020` read the settings, so their effect depends on the environment they
  run in. A dev database restored into another environment keeps the bots, and a database
  migrated before its environment was set to `dev` has none until `0011` and `0020` are re-run.
- The bots' bookings are real rows on dev and count against the grid like any guest's.
- Changing the bot password needs a new migration that sets a new hash on every bot added by
  `0011`, `0018` and `0020`, and the same change in the n8n credential.
- Locally the bots are registered by hand through `/auth/register`, which echoes the code there,
  and `/auth/verify-email` (`n8n/README.md`).

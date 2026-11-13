# 14. Booking simulator on dev

Date: 2026-11-11

## Status

Accepted. Amended 2026-11-13: migration `0018` adds a staff bot on dev and local with the same
bot password.

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
  `n8n/workflows/booking-simulator.json` signs in as a bot, searches tables and books or cancels
  through the public API, every 5 minutes. It never runs against staging or prod.
- **Bots come from an environment-gated data migration.** Migration `0011` inserts four verified
  users, `booking-bot-1@example.com` to `booking-bot-4@example.com`, only when
  `APP_ENVIRONMENT` is `dev`; in every other environment its upgrade and downgrade do nothing. The
  migration runs in the normal deploy (`alembic upgrade head`), so the bots exist on dev without
  access to the server. Its downgrade deletes the four users, and their bookings go with them
  through the `ON DELETE CASCADE` on `bookings.user_id`. A plain insert: if one of the emails is
  already taken on dev, the migration fails loudly instead of adopting a foreign account.
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
- **Bots leave real guests a choice.** The workflow books only where at least 4 fitting tables are
  free at one location and one start time, so it never takes the last tables of a slot.
- **Deployment comes later.** For now n8n runs on the developer machine (`n8n/compose.yml`).
  Running it in the platform stack on the VM is a separate step.

## Alternatives considered

- **Register the bots through the API.** Verification needs the emailed code, which dev does not
  return, so it needs a mailbox per bot or a person reading codes.
- **A registration bypass or a bot flag on users.** Adds a code path or a column to the
  production schema only for a simulator, and a bypass is an attack surface on every environment.
- **Bots in every environment.** On staging and prod the bots would take tables from real guests
  and show up in their data.

## Consequences

- Migration `0011` reads the settings, so its effect depends on the environment it runs in. A dev
  database restored into another environment keeps the bots, and a database migrated before its
  environment was set to `dev` has none until `0011` is re-run.
- The bots' bookings are real rows on dev and count against the grid like any guest's.
- Changing the bot password needs a new migration with a new hash and the same change in the n8n
  credential.
- Locally the bots are registered by hand through `/auth/register`, which echoes the code there,
  and `/auth/verify-email` (`n8n/README.md`).

---
title: 'Booking invites: participants, guests without an account and the invite link'
type: 'feature'
created: '2026-11-11'
status: 'done'
baseline_commit: 'c0b9f2d4f42b607c227ba30a2dfc60472d8e45a9'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/docs/adr/0013-table-booking-slots-and-double-booking.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-edit-booking.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Figma flows let a booking owner share an invite link ("Guest Invite link" modal, `/join/<code>`) and let friends, with or without an account, join the reservation ("You're Invited!" modal with "Enter Your Name"). The backend has no notion of who belongs to a booking, so pre-order (next PRs) has nothing to attach to.

**Approach:** Participants and the guest identity become part of the core bookings feature: every booking has its owner as a participant, and joined guests are participants too, either a signed-in user or a guest known by an httpOnly cookie. A new regular feature `invites` holds the invite code, the public preview and the join route, and delegates the join rules to core bookings.

## Boundaries & Constraints

**Always:**
- Decisions (Vlad, 2026-11-11): owner plus guests never exceed `party_size` (`BOOKING_FULL`); a guest without an account joins by link with a required name; a signed-in user joins with the profile name and gets no guest cookie; no invite rotation; join closes at the pre-order lock, 30 min before the start (`BookingSettings.preorder_lock_minutes`), and when the booking is cancelled (`INVITE_CLOSED`).
- Participants: role `OWNER` or `GUEST`, exactly one of `user_id` / `guest_id`. Booking create adds the owner participant; migration backfills owners of existing bookings. The name shown is the user's `first_name` (as in Figma "Guest: Alex" and the preview's "John invited you") and the entered name for guests. Owner checks keep using `bookings.user_id`, which always equals the `OWNER` participant's `user_id`.
- Guest identity: a `guests` row (name, sha256 hash of a random token, `expires_at`) and the cookie `guest_token` (httpOnly, Secure, SameSite=Lax, path and lifetime from settings). A guest whose cookie is valid reuses that row when joining another booking, keeps its name, and gets `expires_at` and the cookie renewed. An unknown or expired cookie counts as no guest. When the access cookie and the guest cookie both arrive, the user wins.
- Join locks the booking row (`FOR UPDATE`) before counting participants; a signed-in joiner's user row is locked first, because the participant insert takes `FOR KEY SHARE` on it and create and edit hold users `FOR UPDATE` (ADR 13 order: user, table, booking). Joining again (owner, same user, same guest) answers 200 and changes nothing. A signed-in user may join without any overlap check.
- The join route treats a caller with no access cookie as anonymous. The access cookie lives 15 min, so the client refreshes its session before joining; the route description says so.
- Join closes when less than `preorder_lock_minutes` remain before the start, the same boundary rule as the cancel cutoff: exactly 30 min before is still open.
- The booking object of every bookings route gains `role` (the caller's) and `participants` (`id`, `name`, `role`, owner first, then by join time). `GET /bookings` lists owned and joined bookings. `GET /bookings/{booking_id}` is open to any participant, user or guest. Edit and cancel stay owner-only: a guest's id answers 404.
- Edit refuses a `party_size` below the participant count (`PARTY_BELOW_PARTICIPANTS`).

**Never:** removing a guest or a guest leaving (PR 3 with the group pre-order); invite rotation or revocation; carts or pre-order; merging a guest into an account after sign-in; notifications.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Invite link | owner, own `CONFIRMED` booking, asked twice | 200 `{code}`, the same code both times | N/A |
| Link refused | another user's or unknown id / cancelled | no code | 404 `BOOKING_NOT_FOUND` / 409 `BOOKING_ALREADY_CANCELLED` |
| Preview | valid code, anonymous | 200: owner first name, `starts_at`, `ends_at`, `party_size`, table, location | N/A |
| Preview refused | unknown code / booking cancelled / now within 30 min of the start | nothing | 404 `INVITE_NOT_FOUND` / 409 `INVITE_CLOSED` |
| Guest joins | anonymous, name "Alex", party 2 | 200, `role: GUEST`, participants owner + Alex; `Set-Cookie: guest_token`; `GET /bookings/{id}` with that cookie answers the same | N/A |
| No name | anonymous without a valid guest cookie, no body, no name or a blank one | nothing stored | 400 `GUEST_NAME_REQUIRED` |
| Long name | name over 50 characters | nothing stored | 422 `VALIDATION_ERROR` |
| Lock boundary | exactly 30 min / 29 min before the start | 200 / 409 `INVITE_CLOSED` | N/A |
| User joins | signed in, not a participant | 200, participant with the profile name, no guest cookie; the booking appears in the user's `GET /bookings` with `role: GUEST`; edit and cancel answer 404 | N/A |
| Join again | owner / joined user / same guest cookie | 200, participants unchanged | N/A |
| Second booking | guest cookie from booking A joins booking B | 200, same guest in both; both readable with the cookie | N/A |
| Full | party 2, owner + one guest, third person joins | nothing stored | 409 `BOOKING_FULL` |
| Join closed | cancelled booking / within 30 min of the start / unknown code | nothing stored | 409 `INVITE_CLOSED` / 409 `INVITE_CLOSED` / 404 `INVITE_NOT_FOUND` |
| Participant view | no cookies / signed-in non-participant / guest of another booking | nothing | 401 `NOT_AUTHENTICATED` / 404 `BOOKING_NOT_FOUND` / 404 `BOOKING_NOT_FOUND` |
| Create | new booking | 201, `role: OWNER`, participants = the owner | N/A |
| Party below participants | party 3, three participants, edit to party 2 | nothing changed | 409 `PARTY_BELOW_PARTICIPANTS` |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/bookings/` -- `models/booking.py` (add `Guest`, `BookingParticipant`), `enums/` (add `ParticipantRole`), `repositories/booking_repository.py` (`list_for_user` must also return joined bookings), `services/booking_service.py` (`create` adds the owner participant; `edit` gets the participant-count check after the locks; `_to_view` gains role and participants), `dto/booking_view.py`, `schemas/booking.py`, `endpoints/`. Add a participant service for join, the guest lookup and the participant view.
- `backend/src/app/features/core/auth/endpoints/cookies.py` -- `SessionCookies` is the pattern for a cookie writer: `GuestCookies` in bookings endpoints, name `guest_token` as a class constant; handlers that set it build their own response.
- `backend/src/app/features/core/auth/endpoints/dependencies.py:197-205` -- `get_current_user` raises 401 without an access cookie. The join and participant routes need an optional variant: no access cookie means no user, an invalid or expired one stays 401.
- `backend/src/app/features/core/auth/services/session_service.py:88-90` -- `_hash_token` (sha256 hex) to copy for the guest token; `refresh_token_repository.py:18-21` for `populate_existing` on a locked re-read.
- `backend/src/app/features/core/bookings/services/booking_schedule.py` -- add the lock check (`now >= starts_at - preorder_lock_minutes`) here.
- New regular feature `backend/src/app/features/invites/` -- `models/` (`BookingInvite`: `booking_id` PK and FK `bookings` CASCADE, unique `code`, `created_at`), repositories, a service that maps the code to the booking and calls core bookings, endpoints with their own errors map and OpenAPI tag class. It imports only core features (ADR 11); import-linter wildcards already cover it.
- The core API invites calls, each returning a DTO: an owner lookup for the link that locks the booking row (`FOR UPDATE`, `populate_existing`), so two first link requests cannot both insert a code; a preview view with the owner's first name; `join(booking_id, user_id | None, guest_token | None, name | None)` returning the participant booking view plus the guest token to set, if any. `INVITE_CLOSED`, `BOOKING_FULL`, `GUEST_NAME_REQUIRED` and `PARTY_BELOW_PARTICIPANTS` are core bookings exceptions in its `ERROR_STATUSES`; invites owns only `INVITE_NOT_FOUND` and documents the core and auth codes through its own `DOCUMENTED_ERROR_STATUSES`, as `bookings/endpoints/errors.py:43-47` does.
- The optional-user dependency lives in `core/auth/endpoints/dependencies.py` next to `get_current_user`.
- `backend/src/app/model_registry.py`, `backend/src/app/main.py` -- register the new models, router, tag ("Invites" after "Booking") and error statuses.
- `backend/src/app/config/settings.py:130` -- `BookingSettings`; `backend/.env.example` lists every `BOOKING_` key.
- `backend/migrations/versions/0011_add_dev_booking_bots.py` -- latest revision; new ones revise it.
- `backend/tests/test_bookings.py` -- fixtures `fake_clock`, `venue`, `users`, helpers `sign_in`, `book`, `edit`, `assert_error`; extend, do not duplicate. `add_booking` (157-178) inserts bookings directly: it must also insert the `OWNER` participant. `backend/tests/test_database.py` -- constraint tests, failing flush last.
- `backend/tests/conftest.py` -- every test runs in one outer transaction, so `server_default now()` gives every row of a test the same `created_at`: participants get `created_at` from `clock.now()` in the service.
- `backend/src/app/common/database.py:17` -- the `uq` convention names by the first column only, so both participant unique constraints and the partial OWNER index get explicit names (as `oauth_account.py:15-16`); `test_database.py` pins them.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_invites.py` -- API tests for every invite, preview and join row of the matrix and the error orders below -- tests first.
- [x] `backend/tests/test_bookings.py` -- create, list and participant-view rows, the guest's 404 on edit and cancel, `PARTY_BELOW_PARTICIPANTS`.
- [x] `backend/tests/test_database.py`, `test_openapi.py`, `test_settings.py` -- new tables, the exactly-one CHECK and the unique constraints; the routes under "Booking" and "Invites"; new settings with defaults and overrides.
- [x] `backend/migrations/versions/0012_create_booking_participants.py` -- enum `participant_role`, `guests`, `booking_participants`, backfill one `OWNER` row per existing booking; `0013_create_booking_invites.py` -- `booking_invites`. Downgrades drop them.
- [x] `backend/src/app/features/core/bookings/`, `backend/src/app/features/invites/`, `settings.py`, `.env.example`, `model_registry.py`, `main.py` -- as in the Code Map.
- [x] `docs/adr/0016-booking-participants-and-guest-identity.md` -- participants in core, invites as the first regular feature, the guest cookie with a hashed token, the seat rule under the booking lock, and the join lock order (joiner's user, then booking) as an addition to ADR 13.
- [x] `_bmad_output/implementation-artifacts/deferred-work.md` -- the join locks and the first-link race need two concurrent connections to test.

**Acceptance Criteria:**
- Given the local server at the new head, when the owner gets the invite link and an anonymous curl client joins with a name, then the owner's `GET /bookings` shows both participants, the guest reads the booking with its cookie, and a join beyond `party_size` answers 409.
- Given CI, then lint, mypy, import-linter, the migration round trip with `alembic check`, and tests pass.

## Design Notes

- Routes: core `GET /api/v1/bookings/{booking_id}`, declared after `/tables` so `tables` never reaches the uuid parser; invites `GET /api/v1/bookings/{booking_id}/invite` (owner only), `GET /api/v1/invites/{code}` (public), `POST /api/v1/invites/{code}/join`. The join body is optional; `name` is stripped, capped at 50 (longer is 422) and blank counts as missing; it is used only when a new guest is created and ignored for a user or a valid cookie guest. The join answers the participant booking object and sets the cookie only when a guest was created or renewed.
- Descriptions: list, edit, cancel, slots and the Booking tag now speak of owned and joined bookings; the participant view and join mention the `guest_token` cookie; `test_openapi.py` `FLOWS` gets the four new routes and the "Invites" tag.
- Participants load in one query per request (`booking_id IN (...)` for the list), ordered `OWNER` first, then `created_at`, then `id`.
- Codes: `secrets.token_urlsafe(16)`, created on the first link request. Guest token: `secrets.token_urlsafe(32)`, only its sha256 hex is stored.
- Settings: `preorder_lock_minutes` 30, `guest_token_ttl_days` 31, `guest_cookie_path` "/".
- Tables: `guests` (`id`, `name` varchar 50, `token_hash` varchar 64 unique, `expires_at`, `created_at`, `updated_at`); `booking_participants` (`id`, `booking_id` FK CASCADE, `user_id` FK CASCADE null, `guest_id` FK CASCADE null, `role`, `created_at`; `CHECK (num_nonnulls(user_id, guest_id) = 1)`, unique `(booking_id, user_id)`, unique `(booking_id, guest_id)`, a partial unique index on `booking_id` where `role = 'OWNER'`, indexes on `user_id` and `guest_id`).
- Join order: `NOT_AUTHENTICATED` for an invalid access token, `INVITE_NOT_FOUND`, lock the joiner's user row if signed in, lock the booking (`populate_existing`), `INVITE_CLOSED`, already a participant → 200, `GUEST_NAME_REQUIRED`, `BOOKING_FULL` (count with a fresh query under the lock), create or renew the guest, insert, flush. Preview order: `INVITE_NOT_FOUND`, `INVITE_CLOSED`. Link order: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`, `BOOKING_ALREADY_CANCELLED`. Participant view: `NOT_AUTHENTICATED` when there is neither a user nor a valid guest, then `BOOKING_NOT_FOUND`. List: `NOT_AUTHENTICATED`. Edit checks `PARTY_BELOW_PARTICIPANTS` after the locks, before the overlap checks.
- Migrations: 0012 backfills one `OWNER` row per booking with the booking's `user_id` and `created_at` (this covers the dev bot bookings from 0011); its downgrade drops `booking_participants`, then `guests`, then the `participant_role` enum explicitly, as 0010 does for its enum.
- No comments or docstrings in backend code, migrations or tests (Vlad's rule for this project).

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.
- Throwaway `postgres:18`: `alembic upgrade head`, `downgrade 0011`, `upgrade head`, `alembic check` -- clean.

## Implementation Notes

- Join boundary: the Code Map formula `now >= starts_at - preorder_lock_minutes` would close the join at exactly 30 min, which contradicts the frozen Always rule and the Lock boundary row. `BookingSchedule.check_joinable` uses the cancel-cutoff rule instead: closed when `starts_at - now < preorder_lock_minutes`.
- `Guest` and `BookingParticipant` live in `models/booking.py` as the Code Map says; other features keep one model per file. Constraint names: `ck_booking_participants_one_of_user_id_guest_id`, `uq_booking_participants_booking_id_user_id`, `uq_booking_participants_booking_id_guest_id`, `ix_booking_participants_booking_id_owner` (partial, `role = 'OWNER'`), `uq_guests_token_hash`, `uq_booking_invites_code`; `booking_invites.code` is `varchar(32)`. Participant and invite `created_at` have no server default and come from `clock.now()`.
- Core API on `ParticipantService`: `lock_owned` (returns `OwnedBooking(id)`), `preview` (`InvitePreviewView`, field `owner_first_name`), `join` (`JoinOutcome(booking, guest_token)`) and `get_for_participant`. `BookingViewBuilder` builds every booking view with role and participants (one participant query per request) for both `BookingService` and `ParticipantService`.
- A renewed guest keeps its token: the cookie is set again with the same value and a fresh Max-Age, and `expires_at` moves to now + `guest_token_ttl_days`. `GuestCookies.set` does nothing for a `None` token, so the join handler always calls it.
- `test_invites.py` reuses the `test_bookings.py` fixtures and helpers by import; the imported fixtures are listed in `__all__` so ruff does not flag them as unused, and `set_cookies` comes from `test_login.py`. `add_booking` gained `party_size` and inserts the `OWNER` participant; `add_guest`, `add_participant`, `as_guest` and `stored_participants` were added.
- Verified by the implementer: ruff, format check, mypy (209 files), lint-imports (9 kept), pytest 471 passed (three repeated runs of the booking, invite and database tests green). Tests were written before the code, but the red run against the unimplemented code was not recorded. Format mismatches were fixed by hand, the formatter was not run.
- Migration round trip on a throwaway `postgres:18` (port 5439, removed afterwards): `upgrade head`, `alembic check` clean, `downgrade 0011` removes `booking_participants`, `guests`, `booking_invites` and the `participant_role` type, `upgrade head` again backfills one `OWNER` row with the booking's `user_id` and `created_at` for the booking created through the API, `alembic check` clean.
- Live check (server from this worktree on port 8011 against that throwaway database, not the local `app` database): owner registered and verified through the API, Table 1 at 48 Rustaveli Avenue booked for 2026-11-13 12:00 for 2; the invite link answered the same code twice; the anonymous preview showed John, the time, table and location; an anonymous join as Alex answered 200 with `role: GUEST` and `Set-Cookie: guest_token=...; HttpOnly; Max-Age=2678400; Path=/; SameSite=lax; Secure`; the guest read the booking with the cookie; the owner's `GET /bookings` listed John and Alex; a third join answered 409 `BOOKING_FULL`, a nameless one 400 `GUEST_NAME_REQUIRED`, Alex again 200 without a cookie, no cookies 401, an edit to party 1 409 `PARTY_BELOW_PARTICIPANTS`, an unknown code 404 `INVITE_NOT_FOUND`. No 5xx or traceback in the server log.
- Review patches (rows 15, 16, 27-30): settings override test, nameless cookie-guest join, participants in edit and cancel responses, invalid access cookie with a guest cookie, Booking tag text; on Vlad's request the shared booking fixtures moved to `tests/support/` (`booking_fixtures.py` registered through `pytest_plugins`, `bookings.py`, `http.py`), `tests/test_suite_layout.py` fails on any import of a `test_*` module or `conftest`, and `.claude/rules/backend.md` gained a Tests rule. Verified by the orchestrator: ruff, format check, mypy (214 files), lint-imports (9 kept), pytest 477 passed.
- Live check on the local `app` database 2026-11-11 (migrated to `0013` by Vlad; server from this worktree on port 8001): all 41 bookings that existed before `0012` have exactly one `OWNER` participant with the booking's `user_id` (read-only `SELECT`). Owner `edit-check@example.com` booked Table 4 at 48 Rustaveli Avenue for 2026-11-12 14:00 for 3 (`role: OWNER`, participants = owner); the invite code was the same twice; the anonymous preview showed the owner's first name, 14:00–15:30, party 3, table and location; a nameless join 400 `GUEST_NAME_REQUIRED`; "  Alex  " joined as `Alex`, `Set-Cookie: guest_token; HttpOnly; Max-Age=2678400; Path=/; SameSite=lax; Secure`; the guest read the booking with the cookie; joining again answered 200 with no cookie; `invite-check@example.com` (Maria, registered through the API) joined under her first name with no guest cookie, saw the booking in her list as `GUEST`, and got 404 on edit, cancel and the invite link; a fourth person 409 `BOOKING_FULL`; the owner's list showed Edit, Alex, Maria; edit to party 2 409 `PARTY_BELOW_PARTICIPANTS`; no cookies 401; a guest of another booking 404 `BOOKING_NOT_FOUND`; unknown code 404 `INVITE_NOT_FOUND`; after the owner cancelled, preview and join 409 `INVITE_CLOSED` while Alex still read the cancelled booking. Both check bookings cancelled afterwards. No 5xx or traceback in the server log.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | Join deadlocks with create/edit: the participant FK takes `FOR KEY SHARE` on the joiner's user row, which conflicts with their `FOR UPDATE` | high | PostgreSQL row-lock conflict table; `booking_service.py` create and edit lock users. Patched: joiner's user row locked first; ADR 16 records it. |
| 2 | spec review | `add_booking` inserts bookings without an owner participant | medium | `test_bookings.py:157-178`. Patched: Code Map. |
| 3 | spec review | Participant order nondeterministic inside one test transaction | medium | `conftest.py` outer transaction. Patched: `clock.now()`, explicit order, one query. |
| 4 | spec review | Blank name would be 422, the matrix says 400 | medium | Patched: schema rules, matrix rows, name ignored for users and cookie guests. |
| 5 | spec review | Two first link requests race on the PK and answer 500 | medium | Patched: owner lookup locks the booking row. |
| 6 | spec review | An expired access cookie makes a signed-in user join as a guest | medium | Access cookie max-age 15 min. Patched: refresh-before-join contract in Always and the route description. |
| 7 | spec review | Core/invites boundary, exception homes, documented errors, error orders unpinned | medium | Patched: Code Map and Design Notes. |
| 8 | spec review | Both participant unique constraints get the same convention name | low | `database.py:17`. Patched: explicit names. |
| 9 | spec review | Join's locked read needs `populate_existing` | low | `refresh_token_repository.py:18-21`. Patched. |
| 10 | spec review | Lock boundary differs from the cancel cutoff rule | low | `booking_schedule.py` `_cutoff_passed`. Patched: same rule, boundary row. |
| 11 | spec review | Route order, descriptions, OpenAPI flows | low | Patched: Design Notes. |
| 12 | spec review | Migration backfill and downgrade details | low | `0010` drops its enum explicitly. Patched. |
| 13 | spec review | Guests would see full names of user participants while the preview shows a first name | low | Decided: users show by `first_name`, matching Figma and the preview. |
| 14 | verification-gap | 0012 owner backfill never runs on existing bookings in CI | medium | Pre-verified: the test database migrates empty. Route: verified on the local `app` database, which holds bookings from before 0012, with a read-only `SELECT` for bookings without an `OWNER` row during the live check. |
| 15 | verification-gap | New settings never tested with non-default values | low | Pre-verified: every test runs on defaults equal to other values. Patch: one override test for lock, cookie path, max-age and expiry. |
| 16 | verification-gap | A valid cookie guest joining a new booking without a name is never exercised | low | Pre-verified. Patch: nameless variant of the second-booking test. |
| 17 | edge | A participant re-joining after cancel or lock gets `INVITE_CLOSED` | low | Follows the spec's join order; the participant still reads the booking through `GET /bookings/{id}`. Rejected. |
| 18 | edge | A signed-in joiner may sit in two overlapping bookings | low | Frozen Always rule: no overlap check on join. Rejected. |
| 19 | edge | Joiner's user row deleted before the locked read → FK 500 | false | No write path deletes users. |
| 20 | blind | Spec missing from the review diff | false | By design: the spec goes only to the edge-case layer. |
| 21 | blind | Invite link is handed out for bookings that can no longer be joined | low | The preview answers `INVITE_CLOSED`; the Figma card shows Invite Guests only on upcoming bookings. Rejected. |
| 22 | blind | The caller cannot find itself in `participants` | low | No consumer yet; PR 3 (group pre-order, remove guest) adds the caller's participant id. Rejected here. |
| 23 | blind | Preview shows no free seats | low | Figma "You're Invited!" shows only the party size. Rejected. |
| 24 | blind | Expired `guests` rows are never cleaned up and a cleanup would cascade into past participants | low | No cleanup exists; adding one is a separate decision. Rejected. |
| 25 | blind | Guest TTL only covers the visit because 31 > horizon 30; no validator | low | Misconfiguration only; no validator by decision (book-a-table #10). Rejected. |
| 26 | blind | Owner has two sources of truth and the ADR does not admit it | false | ADR 16 states that owner checks use `bookings.user_id` and that every insert path must add the owner participant. |
| 27 | blind | Edit and cancel responses with joined participants untested | low | Patch: assert `participants` in the edit test and a cancel with a guest. |
| 28 | blind | Participant view with an invalid access cookie and a valid guest cookie untested | low | Implementation answers 401 through `OptionalUserDep`. Patch: one test case. |
| 29 | blind | Booking tag text still says everything needs sign-in | low | `openapi_tags.py`. Patch: the view is open to guests by the `guest_token` cookie. |
| 30 | blind | `test_invites.py` imports fixtures from `test_bookings.py` with an `__all__` workaround | low | First cross-module fixture import in the suite. Vlad (2026-11-11): extract the shared fixtures and stop such imports. Patched: `tests/support/` with a `pytest_plugins` fixture module, `tests/test_suite_layout.py` as the guard, a Tests rule in `.claude/rules/backend.md`. |

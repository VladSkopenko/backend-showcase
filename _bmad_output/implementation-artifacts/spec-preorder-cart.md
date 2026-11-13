---
title: 'Pre-order cart: each participant builds and submits their part'
type: 'feature'
created: '2026-11-11'
status: 'in-review'
baseline_commit: 'd79e0df12413129b8b5e025bfee01ad25f186a4e'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/docs/adr/0016-booking-participants-and-guest-identity.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-booking-invites.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Figma Guest Flow (menu with the reservation strip, dish card and modal "Pre-Order", cart drawer with steppers and "Submit Pre-Order", "Pre-Order Submitted" with "Create New Pre-Order") and the owner's "Add Pre-Order" have no backend: a participant cannot pick dishes for the visit.

**Approach:** A new regular feature `preorder`. Every participant of a booking, owner and guests alike, keeps a server-side draft cart for that booking and submits it into the booking's group pre-order; a submitted part is read-only for its author, and a new draft can follow. Core menu gains `prep_minutes` for the "Expected ready time" line, and booking responses tell the caller which participant they are.

## Boundaries & Constraints

**Always:**
- Decisions (Vlad, 2026-11-10/11): the cart lives on the server and survives reloads and sign-outs; each participant has their own draft; the owner uses the same draft and submit as guests; one draft line per dish with a quantity and one note; a submitted part goes to the group and its author never edits or withdraws it; guests see only their own items; pre-order closes 30 min before the start (`BookingSettings.preorder_lock_minutes`, the same boundary as join) and when the booking is cancelled; `Dish.prep_minutes` exists.
- Identity: the caller is a participant through the access cookie or the `guest_token` cookie, exactly as for `GET /bookings/{booking_id}`; no participant → 401 `NOT_AUTHENTICATED`, not a participant of this booking → 404 `BOOKING_NOT_FOUND`.
- Writes (set a line, remove a line, submit) lock the booking row first (`FOR UPDATE`, `populate_existing`) and refuse a cancelled booking or one inside the lock window with 409 `PREORDER_CLOSED`. Reads stay open after the lock.
- A dish must exist (404 `DISH_NOT_FOUND`) and be available to be added or raised (409 `DISH_UNAVAILABLE`); lowering, the note and removal work on an unavailable dish. Quantity runs from 1 (schema, 422 below it) to `PreorderSettings.max_item_quantity` (20; the service refuses more with 400 `QUANTITY_TOO_LARGE`, as `PARTY_TOO_LARGE` does); the note is stripped, at most 200 characters, blank means none.
- Prices are the menu's current `price_cents` at read time; the price is fixed later, when the owner sends the group to the restaurant (next PR). Every line shows the dish's `is_available` and `prep_minutes`.
- Submit moves every draft line into one new submitted part of the caller (a new `submission_id` and one `submitted_at` on its lines) and leaves an empty draft. An empty draft → 409 `CART_EMPTY`; any unavailable dish in the draft → 409 `DISH_UNAVAILABLE` and nothing moves.
- `Dish.prep_minutes` (minutes, > 0) is filled by a data migration by category: appetizers 10, main courses 20, desserts 10, and is returned by the menu routes.
- Every booking object gains `participant_id`: the caller's own participant.

**Never:** the owner's group view, editing another participant's lines, removing a guest (next spec, 3b); sending to the restaurant, price snapshots, statuses or the "x/N" counter (PR 4); notifications or live updates; carts without a booking.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Add | guest, empty draft, dish A quantity 1, note "No onions please" | 200 cart: one line A × 1 with note, dish price, `is_available`, `prep_minutes`; total = price | N/A |
| Change | the same dish A with quantity 3, no note | one line A × 3, note cleared, total = 3 × price | N/A |
| Remove | remove dish A | empty cart, total 0 | N/A |
| Remove missing | dish not in the draft | nothing changes | 404 `CART_ITEM_NOT_FOUND` |
| Bad line | unknown dish / unavailable dish raised or added / quantity 0 / quantity 21 / note over 200 | nothing changes | 404 `DISH_NOT_FOUND` / 409 `DISH_UNAVAILABLE` / 422 `VALIDATION_ERROR` / 400 `QUANTITY_TOO_LARGE` / 422 `VALIDATION_ERROR` |
| Became unavailable | draft has A, A turns unavailable | cart shows A with `is_available: false`; lowering and removal work | N/A |
| Nothing yet | no submit so far | cart empty, total 0; "my submitted items" has no parts, total 0 | N/A |
| Submit | draft A × 2, B × 1 | 200: the submitted part (id, `submitted_at`, lines, total); the draft is empty; "my submitted items" has this one part | N/A |
| Submit again | after a new draft C × 1 | two parts, oldest first, each with its own lines and total, plus the overall total | N/A |
| Submit refused | empty draft / draft with an unavailable dish | nothing moves | 409 `CART_EMPTY` / 409 `DISH_UNAVAILABLE` |
| Closed | cancelled booking / 29 min before the start; exactly 30 min | writes refused; reads answer / allowed | 409 `PREORDER_CLOSED` / N/A |
| Who | no cookies / participant of another booking / owner | — / — / same cart rules as a guest | 401 `NOT_AUTHENTICATED` / 404 `BOOKING_NOT_FOUND` / N/A |
| Own only | guest Alex and guest Maria each add a dish | each cart and each "my submitted items" shows only its owner's lines | N/A |
| Menu | `GET /menu/dishes` | every dish has `prep_minutes`: 10 for appetizers, 20 for main courses, 10 for desserts | N/A |
| Who am I | any booking response | `participant_id` equals the caller's entry in `participants` | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/bookings/services/participant_service.py` -- `get_for_participant` resolves the caller (user wins over a guest cookie). Add a core method that resolves the caller's participant for a booking and returns a DTO with `participant_id` and `preorder_open` (the booking is `CONFIRMED` and inside the window), plus a locking variant. The locking query locks only the booking row: `with_for_update(of=Booking)` with `populate_existing`, and no join to `dining_tables`, because edit locks the table before the booking. `preorder` raises its own `PREORDER_CLOSED` from `preorder_open`; it never reads booking tables itself.
- `backend/src/app/features/core/bookings/services/booking_schedule.py` -- add `preorder_open(starts_at) -> bool` holding the window rule (`starts_at - now < preorder_lock_minutes` is closed) and use it inside `check_joinable`, so join and pre-order close together.
- `participant_id` on every booking view (`booking_view_builder.py`, `dto/booking_view.py`, `schemas/booking.py`): `list_for_user` and `get_for_participant` select `BookingParticipant.id` next to the role; `get_for_user` (cancel, edit) joins the `OWNER` participant; `create` uses the flushed owner row; `join` uses the existing or the new row.
- `backend/src/app/features/core/bookings/endpoints/dependencies.py` -- `GuestTokenCookie`; `core/auth/endpoints/dependencies.py` -- `OptionalUserDep`.
- `backend/src/app/features/core/menu/` -- `models/dish.py` (add `prep_minutes`), `dto/dish_view.py`, `schemas/dish.py` (`DishCardResponse` gets it), `services/dish_catalog_service.py` (add a lookup of several dishes by id for cart reads, one query), `dto/dish_seed_entry.py` and `services/dish_seed_service.py` (the local seed upserts dishes from a git-ignored `dishes.json`: `prep_minutes` is optional there and defaults by category), `repositories/dish_repository.py:15-28` (`CONTENT_COLUMNS` gets `prep_minutes`, so a re-seed updates it). The column has no server default: every test that builds a `Dish` (`make_dish` in `test_menu.py` and others) passes it. The check is named `prep_minutes_positive` (→ `ck_dishes_prep_minutes_positive`).
- New regular feature `backend/src/app/features/preorder/` -- `models/` (`PreorderItem`), repositories, a service, endpoints with errors map, `DOCUMENTED_ERROR_STATUSES` for the auth, bookings and menu codes it raises through, and an OpenAPI tag class. It imports only core features (ADR 11).
- `backend/src/app/config/settings.py`, `backend/.env.example`, `backend/tests/conftest.py:53` -- new `PreorderSettings` (`PREORDER_` prefix, `max_item_quantity` 20) as `preorder` on the root `Settings`, like `booking`; `"PREORDER_"` joins the cleared prefixes.
- `backend/src/app/model_registry.py`, `backend/src/app/main.py` -- model, router, tag ("Pre-order" after "Invites"), error statuses.
- `backend/tests/support/` -- shared booking fixtures and helpers (`booking_fixtures.py`, `bookings.py`, `http.py`); add pre-order helpers there only if two modules use them. Test modules never import each other (`tests/test_suite_layout.py`).
- `backend/migrations/versions/0013_create_booking_invites.py` -- latest revision.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_preorder.py` -- API tests for every matrix row and the error orders below -- tests first.
- [x] `backend/tests/test_menu.py`, `test_menu_data_migration.py`, `test_seed_menu.py`, `test_bookings.py`, `test_invites.py`, `test_database.py`, `test_openapi.py`, `test_settings.py` -- `prep_minutes` in menu responses (`test_menu` deletes every dish, so the 10/20/10 values are checked in `test_menu_data_migration`; the seed default by category and an explicit value in `test_seed_menu`); `participant_id` in booking responses; the new column and check on `dishes`, the new table, constraints and index; routes under "Pre-order"; `PreorderSettings` defaults and overrides.
- [x] `backend/migrations/versions/0014_add_dish_prep_minutes.py` -- add the column, fill it by category, then set NOT NULL and `CHECK (prep_minutes > 0)`; `0015_create_preorder_items.py` -- enum `preorder_item_state`, table `preorder_items`. Downgrades reverse them.
- [x] `backend/src/app/features/core/menu/`, `core/bookings/`, `features/preorder/`, `settings.py`, `.env.example`, `model_registry.py`, `main.py` -- as in the Code Map.
- [x] `docs/adr/0017-preorder-parts-per-participant.md` -- per-participant drafts submitted into one group, live prices until the restaurant send, the pre-order window shared with join, booking-row lock for every pre-order write (and that 3b's remove-guest must lock the booking first).
- [x] `_bmad_output/implementation-artifacts/deferred-work.md` -- double submit and concurrent PUTs on one dish are serialised by the booking lock; the shared-connection harness cannot observe it.

**Acceptance Criteria:**
- Given the local server at the new head, when a guest and the owner each fill and submit a cart through curl, then each sees only their own submitted items, a second submit keeps both parts, and writes after a cancel answer 409.
- Given CI, then lint, mypy, import-linter, the migration round trip with `alembic check`, and tests pass.

## Design Notes

- Routes: `GET /api/v1/bookings/{booking_id}/cart`; `PUT /api/v1/bookings/{booking_id}/cart/items/{dish_id}` (body `quantity`, optional `note`; answers the cart); `DELETE /api/v1/bookings/{booking_id}/cart/items/{dish_id}` (answers the cart); `POST /api/v1/bookings/{booking_id}/cart/submit` (answers the submitted part); `GET /api/v1/bookings/{booking_id}/my-pre-order` (`parts` oldest first, each `id`, `submitted_at`, `items`, `total_cents`; plus the overall `total_cents`).
- Cart and part lines: `items` (`id`, `dish` {`id`, `name`, `price_cents`, `image_url`, `is_available`, `prep_minutes`}, `quantity`, `note`, `line_total_cents`), `total_cents`.
- Table `preorder_items`: `id`, `participant_id` FK `booking_participants` CASCADE (the booking comes through the participant; no separate `booking_id`), `dish_id` FK `dishes` RESTRICT, `quantity` (`CHECK (quantity > 0)`), `note` varchar 200 null, `state` (`DRAFT` / `SUBMITTED`), `submission_id` uuid null and `submitted_at` null (set together on submit), `created_at` and `updated_at` from `clock.now()` (a PUT on an existing line keeps `created_at`); partial unique index `ix_preorder_items_participant_id_dish_id_draft` on `(participant_id, dish_id)` where `state = 'DRAFT'`; index on `participant_id` (review row 17); CHECK `submission_matches_state` ties `state`, `submission_id` and `submitted_at` (review row 12). Lines order by `created_at`, then `id`; parts by `submitted_at`, then `submission_id`. Tests advance the fake clock between writes, since it is frozen.
- Removing a guest in 3b deletes their pre-order with them (Figma "remove Alex and his pre-order"), which the participant CASCADE allows; 3b locks the booking first.
- Error orders. Reads: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`. Set: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`, lock, `PREORDER_CLOSED`, `QUANTITY_TOO_LARGE`, `DISH_NOT_FOUND`, `DISH_UNAVAILABLE` (add or raise only). Remove: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`, lock, `PREORDER_CLOSED`, `CART_ITEM_NOT_FOUND`. Submit: `NOT_AUTHENTICATED`, `BOOKING_NOT_FOUND`, lock, `PREORDER_CLOSED`, `CART_EMPTY`, `DISH_UNAVAILABLE`. Body validation (422) comes first, as FastAPI does.
- Pre-order writes take only the booking lock; join takes the joiner's user, then the booking; edit takes user, table, booking (ADR 13). No write here locks users or tables, so no cycle. Line inserts take `FOR KEY SHARE` on the dish and participant rows; nothing locks those `FOR UPDATE` today. The booking lock serialises a double submit (the second answers `CART_EMPTY`) and concurrent PUTs on one dish; the partial index is the backstop.
- No comments or docstrings in backend code, migrations or tests (Vlad's rule for this project).

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.
- Throwaway `postgres:18`: `alembic upgrade head`, `downgrade 0013`, `upgrade head`, `alembic check` -- clean.

## Implementation Notes

- Core API on `ParticipantService`: `get_participant` and `lock_participant` return `ParticipantAccess(participant_id, preorder_open)`; both resolve the caller as `get_for_participant` does (shared `_caller_guest_id`). `BookingRepository.get_participation` selects `Booking` and `BookingParticipant.id` with no `dining_tables` join; the locking variant uses `with_for_update(of=Booking)` and `populate_existing`. `BookingSchedule.preorder_open` holds the window rule and `check_joinable` uses it.
- `participant_id` sources: `list_for_user` and `get_for_participant` select `BookingParticipant.id`; `get_for_user` joins the `OWNER` participant and now returns `(booking, table, owner_participant_id)`, so `_get_editable`, `lock_owned`, cancel and edit unpack three values; create uses the flushed owner row; join uses the existing or the new row. `BookingViewBuilder.one` and `many` take the participant id.
- `DishCatalogService.get_many` (one `IN` query, `{}` without a query for no ids) feeds every cart and part read; set uses `DishCatalogService.get`, so `DISH_NOT_FOUND` comes from core menu. Cart lines carry the core `DishView`; `CartDishResponse` picks its six fields. The seed default by category lives in `DishSeedService.DEFAULT_PREP_MINUTES`.
- `add_guest` and `add_participant` moved from `test_bookings.py` to `tests/support/bookings.py`, since `test_preorder.py` uses them too.
- README lists ADR 17, as it lists ADR 16.
- Verified: red run before the code (39 failures in the changed modules, collection errors in `test_preorder.py` and `test_database.py`); then ruff, format check, mypy (238 files), lint-imports (9 kept), pytest 538 passed. Format mismatches were fixed by hand from `ruff format --diff`; the formatter was not run.
- Migration round trip on a throwaway `postgres:18` (port 5439, removed afterwards): `upgrade head`, `alembic check` clean, `downgrade 0013` removes `preorder_items`, the `preorder_item_state` type and `dishes.prep_minutes`, `upgrade head` again fills 10/20/10 by category, `alembic check` clean.
- Live check (server from this worktree on port 8015 against that throwaway database, mail disabled through empty `EMAIL_*`): owner registered, verified and booked through the API; `participant_id` matched the owner on create and the guest on join; the menu answered `prep_minutes` 10/20/10; guest Alex added a dish with a padded note (stored stripped) and a second dish, 21 portions answered 400 `QUANTITY_TOO_LARGE`, removing a missing dish 404 `CART_ITEM_NOT_FOUND`, submit answered the part, a second submit 409 `CART_EMPTY`, a new draft and submit gave two parts (total 7700); the owner filled and submitted one part and saw only it (3600) while Alex still saw his two; no cookies 401; after the owner cancelled, PUT, DELETE and submit answered 409 `PREORDER_CLOSED` while the cart and "my pre-order" still answered 200. No 5xx or traceback in the server log.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | A schema cannot read `max_item_quantity`; the 422 for 21 would ignore the setting | high | `booking_schedule.py` `PARTY_TOO_LARGE` precedent. Patched: schema `ge=1`, service 400 `QUANTITY_TOO_LARGE`; matrix row updated. |
| 2 | spec review | Window rule owner unclear; `check_joinable` raises `INVITE_CLOSED` | high | `booking_schedule.py:90-92`. Patched: `preorder_open` in core, DTO carries it, preorder raises its own error. |
| 3 | spec review | A plain `FOR UPDATE` on the participant query also locks the table row → deadlock with edit | medium | `booking_repository.py` `get_for_participant` joins `dining_tables`. Patched: `of=Booking`, no table join. |
| 4 | spec review | `participant_id` is not available at most call sites | medium | `get_for_user`, `list_for_user`, `get_for_participant`. Patched: Code Map lists each source. |
| 5 | spec review | `my-pre-order` shape and grouping undefined; frozen clock merges parts | medium | `support/bookings.py` FakeClock. Patched: `submission_id`, exact shape, empty row, clock advance. |
| 6 | spec review | `test_menu` deletes every dish, so the 10/20/10 values cannot be checked there | medium | `test_menu.py:58-60`. Patched: data-migration and seed tests. |
| 7 | spec review | Seed `CONTENT_COLUMNS`, test dish builders and the check name missing | medium | `dish_repository.py:15-28`. Patched. |
| 8 | spec review | Index name, `dish_id` ondelete, redundant `booking_id`, cascade on guest removal | low | Patched: named index, RESTRICT, `booking_id` dropped, removal note for 3b. |
| 9 | spec review | `preorder` on root `Settings` and the cleared prefix | low | `settings.py`, `conftest.py:53`. Patched. |
| 10 | spec review | Concurrency notes and deferred tests | low | Patched: Design Notes, deferred-work task, ADR 17 task. |
| 11 | orchestrator | `submitted_at` leaves the API in UTC while every other datetime is in restaurant time | medium | ADR 13 "every datetime leaves the API in the restaurant time zone"; Implementation Notes line on UTC. Patch. |
| 12 | edge, blind | No CHECK ties `state`, `submission_id` and `submitted_at`; `get_my_preorder` silently skips inconsistent rows | low | `preorder_service.py` None checks; workflow.md "fix wrong data where it is written". Patch: CHECK in model and 0015, the service no longer skips. |
| 13 | edge | Submit accepts lines above a lowered `max_item_quantity` | low | Needs a settings change between PUT and submit. Rejected. |
| 14 | edge | `max_item_quantity` of 0 or less blocks every PUT | low | Misconfiguration; no validator by decision. Rejected. |
| 15 | verification-gap | `my-pre-order` order only seen in physical insertion order | low | Pre-verified. Patch: rewrite the first part's rows before asserting. |
| 16 | verification-gap | Owner-only join in `get_for_user` not pinned when a guest row comes first physically | low | Pre-verified; the reviewer suggested defer, but the test fix is one UPDATE. Patch. |
| 17 | blind | `participant_id` has no plain index and `ix_preorder_items_submission_id` serves no query | low | `list_submitted` and the 3b cascade filter by participant; the project indexes FKs. Patch: index `participant_id`, drop the `submission_id` index; Design Notes follow the code. |
| 18 | blind | ADR 17 and deferred-work call the partial index the backstop for a double submit | low | The index only backstops two PUTs of one dish. Patch wording. |
| 19 | orchestrator, blind | `README.uk.md` lacks ADR 17; the API feature line and the Swagger groups list miss Invites and Pre-order | low | Patch both READMEs. |
| 20 | blind | Clients cannot learn whether pre-order is open before a 409 | medium | Figma's disabled "Create New Pre-Order" needs it; the plan puts the lock and statuses in PR 4. Defer (deferred-work). |
| 21 | blind | `max_item_quantity` is not discoverable | low | backend.md: limits are named without numbers; no settings route asked. Rejected. |
| 22 | blind | Submit answers 200 although it creates a part | low | Submit is a transition like cancel, which answers 200. Rejected. |
| 23 | blind | `DISH_UNAVAILABLE` names no dish | low | ADR 12: `details` only on validation errors; the cart shows `is_available`. Rejected. |
| 24 | blind | No limit on the number of submitted parts | low | Only invite-link holders can write; rate limits are out of scope. Rejected. |
| 25 | blind | "User wins over guest cookie" untested on pre-order routes | low | Patch: a non-participant user with a participant guest cookie answers 404. |
| 26 | blind | `_identity(None, None)` would match the owner row | low | Unreachable: `_caller_guest_id` raises first; the guard would protect state not shown reachable. Rejected. |
| 27 | blind | `DEFAULT_PREP_MINUTES` misses a future category | low | A new category needs a migration anyway; dev-only seed. Rejected. |

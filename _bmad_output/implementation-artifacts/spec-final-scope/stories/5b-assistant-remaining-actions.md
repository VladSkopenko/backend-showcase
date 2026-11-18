---
title: 'Assistant: the remaining confirmed actions'
type: 'feature'
created: '2026-11-18'
status: 'done'
baseline_commit: 'c1cca5cc37dcc0338f2ebf850e30e27cdd33ce7d'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/assistant.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/stories/5a-assistant-confirmed-booking.md'
  - '{project-root}/docs/adr/0020-assistant-composes-ai-tools.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The assistant books a table through a card but cannot change or cancel a booking, fill the cart or send the guest's pre-order part; it sends the guest to the website for those.

**Approach:** Five more actions on the mechanism of story 5a, each a dry-run propose tool and an applier in the feature's `ai_tools`, calling the same service as the HTTP route (CAP-7 complete). No change to the mechanism, the routes, the events or the action object.

## Boundaries & Constraints

**Always:**
- Every action follows 5a: the tool dry-runs the route's service in a rolled-back session, reading what the card needs in that same session first; a `DomainError` reaches the model and makes no card; success fills the sink; the applier runs the same service with the pinned payload and the JWT user inside the apply savepoint and returns `result`; one proposal per turn across all kinds, one pending card per session. Money in `result` is a string as `usd()` ("24.00"); on cards it is "$24.00". Dates and times are restaurant-local in the 5a formats.
- **`edit_booking(booking_id, time?, party_size?, duration_minutes?)`** → `booking.edit`, `BookingService.edit`. At least one optional value is required, and a call that changes nothing answers `{"error": "NOTHING_TO_CHANGE"}` with no card. The current booking is read with `ParticipantService.get_for_participant`; omitted values keep its current ones (duration = `ends_at − starts_at` in minutes); `starts_at` is built with `BookingSchedule.start_at` on the booking's local date. Payload pins the new `starts_at`, `party_size`, `duration_minutes` and the "before" values. The applier first compares the booking's current start, party and duration with the pinned "before" and fails with `BOOKING_CHANGED` ("The booking changed after this card was made.") when they differ. Card "Change the booking": Location, Table, Date, Time ("20:00 – 21:30"), Guests, Before ("19:00 – 20:30, 4 guests"); `confirm_label` "Change". `result` `{booking_id, status}`.
- **`cancel_booking(booking_id)`** → `booking.cancel`, `BookingService.cancel` (a `CONFIRMED` booking or a `PENDING` request). Card "Cancel the booking": Location, Table, Date, Time, Guests; `notice` "This cannot be undone."; `confirm_label` "Yes, cancel it". `result` `{booking_id, status}`.
- **`set_cart_item(booking_id, dish_id, quantity, note?)`** → `cart.set_item`, `PreorderService.set_item` with `user_id` (never a guest token). Arguments: `quantity` ≥ 1, the new total for that dish, not an addition; `note` stripped, at most 200 characters; omitted, the line keeps its current note. Card "Update your pre-order cart": Booking ("Fri, 20 Nov 2026, 19:00, 48 Rustaveli Avenue", from `ParticipantService.get_for_participant`), Dish, Quantity, Note (when the line will have one), Line total; `confirm_label` "Save". `result` `{booking_id, cart_total}`.
- **`remove_cart_item(booking_id, dish_id)`** → `cart.remove_item`, `PreorderService.remove_item`. Card "Remove from your pre-order cart": Booking, Dish, Quantity (read with `get_cart` before the removal); `confirm_label` "Remove". `result` `{booking_id, cart_total}`.
- **`submit_preorder(booking_id)`** → `preorder.submit`, `PreorderService.submit`. Payload pins the draft as `[{dish_id, quantity}]` (notes do not count). The applier runs `submit` and compares the submitted lines, by `dish_id` and ignoring order, with the pinned draft; when they differ it raises `CartChangedError` (`CART_CHANGED`, "The cart changed after this card was made.") inside the savepoint, so nothing is submitted. Card "Send your pre-order": Booking, Items ("2 × Chicken Chkmeruli, 2 × Spinach & Feta Khachapuri"), Total; `notice` "A sent part is final; a new cart can follow."; `confirm_label` "Send". `result` `{booking_id, part_id, total}`.
- `BOOKING_CHANGED` and `CART_CHANGED` are `DomainError`s in the owning feature's `services/exceptions.py`, unmapped to HTTP because no route raises them.
- The history line reads `[Proposed <kind>: <status>]` for every kind, with the error code when `FAILED`.
- The system prompt: the "not available yet" rule goes. Each change is proposed as a card as soon as the guest names what to change, with ids taken from `list_my_bookings`, `get_my_preorder` and `list_menu`, never invented. Bookings are changed or cancelled only where the guest's `role` is `OWNER`; a booking stays on its day, so a move to another day is explained, not proposed. Adding a dish already in the cart proposes the new total. Sending the pre-order is proposed only when the guest asks to send it.
- `docs/assistant-frontend-task.md`: the card section lists the six kinds with title, confirm label and `result` shape, the error codes `BOOKING_CHANGED` and `CART_CHANGED`, and says a card is rendered from its fields alone, whatever the kind.

**Never:** New routes, events, statuses or columns; a guest-token caller; editing another participant's lines; submitting for anyone but the caller; a change outside the route's own service; card text in other languages.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Edit proposed and applied | owner moves a CONFIRMED booking from 19:00 to 20:00, same day | card Time "20:00 – 21:30", Before "19:00 – 20:30, 4 guests"; nothing changes until Apply; after Apply the booking starts at 20:00 | N/A |
| Edit with nothing to change | no optional values, or the current ones | `NOTHING_TO_CHANGE`, no card | N/A |
| Edit refused | a taken slot, or a joined guest's booking | the service's error to the model, no card | N/A |
| Edited elsewhere | the booking changes on the website between the card and Apply | Apply `FAILED` `BOOKING_CHANGED`; the booking keeps the website's values | N/A |
| Cancel | owner cancels a CONFIRMED booking; and a PENDING request | card with the notice; after Apply each is `CANCELLED` | N/A |
| Cancel too late | inside the cancel cutoff | `CANCELLATION_CLOSED`, no card | N/A |
| Set item | dish not in the cart, quantity 2 with a note; then the same dish, quantity 3, no note | first Apply: 2 with the note; second card sets 3 and keeps the note; Apply leaves 3, not 5 | N/A |
| Set item refused | an unavailable dish; a quantity above the limit | `DISH_UNAVAILABLE`, `QUANTITY_TOO_LARGE`, no card | N/A |
| Bad arguments | quantity 0; a 201-character note | an error tool message naming the field, no card | N/A |
| Remove | a dish in the cart | card with its quantity; after Apply it is gone | N/A |
| Remove missing | a dish not in the cart | `CART_ITEM_NOT_FOUND`, no card | N/A |
| Pre-order closed | a cart change or submit inside the pre-order lock | the service's error, no card | N/A |
| Submit | a draft of two lines | card with items and total; after Apply `GET /my-pre-order` has the part and the cart is empty | N/A |
| Cart changed | a line is added between the card and Apply | Apply `FAILED` `CART_CHANGED`; nothing submitted, the draft stays | N/A |
| Empty cart | submit with no drafts | the service's error, no card | N/A |
| Not a participant | a cart or submit action on a booking the user has not joined | `BOOKING_NOT_FOUND`, no card | N/A |
| One per turn | `set_cart_item` then `cancel_booking` in one turn | the second answers `ONE_PROPOSAL_PER_TURN` | N/A |
| History | a FAILED `preorder.submit` | `[Proposed preorder.submit: FAILED CART_CHANGED]` | N/A |

</frozen-after-approval>

## Code Map

- `backend/tests/support/` -- first move the pre-order helpers local to `tests/test_preorder.py:77-212` (`menu`, `make_dish`, `add_party`, `put_item`, `submit`, `get_cart`, `my_preorder`, `fill`) into a support module and register any fixtures in `tests/conftest.py`, since test modules may not import each other (`tests/test_suite_layout.py`).
- `backend/src/app/features/core/bookings/ai_tools/` -- `edit_booking`, `cancel_booking` beside `create_booking`; one applier per file (backend.md): `booking_create_applier.py` (moved), `booking_edit_applier.py`, `booking_cancel_applier.py`; args in `arguments.py`. Services unchanged: `booking_service.py:105-168` (`cancel`, `edit`), `booking_schedule.py:46` (`start_at`), `participant_service.py:141-153` (`get_for_participant`). `BookingChangedError` in `core/bookings/services/exceptions.py`.
- `backend/src/app/features/preorder/ai_tools/` -- the three tools in `preorder_tools.py`, args in `arguments.py` (`quantity` `ge=1`; note stripped, `max_length=200`, as `preorder/schemas/preorder.py:9-14` but without importing it), `cart_set_item_applier.py`, `cart_remove_item_applier.py`, `preorder_submit_applier.py`; `PreorderService` built as `preorder/endpoints/dependencies.py:16-28`; `preorder_service.py:50-145` unchanged. `CartChangedError` in `preorder/services/exceptions.py`.
- `backend/src/app/common/ai_tools.py` -- reused; `usd()` for money.
- `backend/src/app/features/assistant/services/toolkit_builder.py` -- the new appliers in the registry; `system_prompt_builder.py:37-39` -- the rule replaced.
- `backend/tests/test_assistant_more_actions.py` -- the matrix.
- `docs/assistant-frontend-task.md:124-132` -- the kinds table; `docs/roadmap.md` -- tick "AI assistant actions"; `README.md:32,143`, `README.uk.md:31,143` -- the assistant row says it changes bookings and the cart through cards; the "What is next" line goes.

## Tasks & Acceptance

**Execution:**
- [x] Move the pre-order test helpers to `tests/support/` -- test infrastructure.
- [x] Tests for the matrix, written first and failing -- contract.
- [x] Booking edit and cancel tools and appliers; cart and submit tools and appliers; errors; registry; prompt -- behaviour.
- [x] Frontend task document, roadmap, README -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean.
- Given the local API with Vlad's key, when a verified user in Russian moves their booking to 20:00, adds two khachapuri to its pre-order cart, sends the pre-order and then cancels the booking, each through a card and Apply, then each change shows in the routes only after its Apply, and every card and comment matches what happened.

## Implementation Notes

- 2026-11-18: implemented by a subagent. Pre-order helpers moved to `tests/support/preorder.py` with the `menu` and `party` fixtures in `tests/support/preorder_fixtures.py` (registered in `conftest.py`). `edit_booking` and `cancel_booking` in `BookingTools` with `booking_create_applier.py` (moved), `booking_edit_applier.py`, `booking_cancel_applier.py`; `set_cart_item`, `remove_cart_item`, `submit_preorder` in `PreorderTools` with one applier per file and a `PreorderServices` builder shared by the tools and appliers. The edit payload pins `before` as `{starts_at, party_size, duration_minutes}`; the set-item payload pins the resolved note (an omitted note becomes the line's current one at proposal). `test_assistant_tools.py` and `test_assistant_actions.py` lost the "not available yet" prompt pin and gained the five tool names. 911 tests, ruff, format check, mypy (365 files) and 11 import contracts clean. Review and the live check are still open.

- 2026-11-18, parent session after the review patches: 920 tests, ruff, format check, mypy (365 files), 11 import contracts clean. Live, local `app` at 0024, API on port 8010 with Vlad's key: a verified `live5b-…@example.com` with one booking (Table 3, Fri 20 Nov 2026 19:00, 2 guests) asked in Russian, each through a card and Apply: "move my booking to 20:00" → `booking.edit` card Time "20:00 – 21:30", Before "19:00 – 20:30, 2 guests", the booking unchanged until Apply, then 20:00–21:30; "add two spinach and feta khachapuri" → `cart.set_item` card Quantity 2, Line total $36.00, then the cart holds 2; "send my pre-order" → `preorder.submit` card Items "2 × Spinach & Feta Khachapuri", Total $36.00, then `my-pre-order` totals 36.00 and the cart is empty; "cancel this booking" → `booking.cancel` card with the notice and "Yes, cancel it", then CANCELLED. Every comment was in Russian and matched the outcome. Asked for "Adjarian khachapuri", the model said the menu has none and offered Spinach & Feta Khachapuri, which is the only khachapuri in the local menu.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Live check: the model asked the guest for the booking's date and party size instead of looking it up, so no card came | high | four Russian requests without a card | patch: call `list_my_bookings` first, use the only matching booking, find dishes with `list_menu` |
| Live check: the model said "I added" before Apply | low | the next sentence asks to confirm on the card; nothing changes before Apply | rejected |
| Code review: the edit "before" check reads without a lock before `edit` locks (edge-case, blind) | medium | a website edit in between passes the check | patch: `ParticipantService.lock_owned` first |
| Code review: `BOOKING_CHANGED` guarded only for the party size; party and duration edits untested (verification-gap, blind) | medium | one test changes the party size only | patch: parametrized and new tests |
| Code review: the set-item card hides the current quantity and the applier overwrites website changes (blind, edge-case) | medium | absolute pinned values, no "Before" | patch: "Before" field, pinned snapshot, `CART_CHANGED` |
| Code review: the submit total is shown but not checked (blind, edge-case) | low | a price change submits an unseen total | patch: pin and compare `total_cents` |
| Code review: an empty note clearing it is untested (verification-gap, blind) | low | only the omitted path is tested | patch: test |
| Code review: cancel refusals barely tested (blind) | low | only the cutoff | patch: joined and already cancelled |
| Code review: a time with an offset is silently stripped (edge-case) | low | `datetime.combine` | patch: reject aware times |
| Code review: `NOTHING_TO_CHANGE` outside `AiToolErrors`, unexplained (blind) | low | | patch |
| Code review: two booking label formatters (blind) | low | | patch: one source, `BookingSchedule` |
| Code review: the stale-check mechanism not recorded (blind) | low | workflow rule 5 | patch: ADR 20 |
| Code review: manual checks miss remove and `CART_CHANGED` (blind) | low | doc checklist | patch |
| Code review: the cancel and remove cards are not checked against later changes (edge-case, blind) | false | they act on the identity of the booking or line, not on the values shown; recorded in ADR 20 | rejected |
| Code review: remove gives `CART_ITEM_NOT_FOUND` when a line is added between the reads (edge-case) | low | a line added in a millisecond window | rejected |
| Spec review: the draft comparison before `submit` can be bypassed by a commit in between | high | `get_cart` reads without the lock taken by `submit` | patch: compare the submitted lines inside the savepoint |
| Spec review: `CART_CHANGED` type and home unstated | medium | only `DomainError` becomes FAILED | patch: `CartChangedError` in `services/exceptions.py` |
| Spec review: "another day" cannot reach the edit service | medium | no date argument | patch: row dropped; the prompt explains instead |
| Spec review: the current values for omitted edit arguments have no source; no stored duration | medium | `booking_service.py:120-135` | patch: `get_for_participant`, duration from the period |
| Spec review: an edit with nothing to change makes a card | low | `edit` accepts it | patch: `NOTHING_TO_CHANGE` |
| Spec review: edit card labels and formats unclear | low | | patch |
| Spec review: an edit applied over a website change overwrites it | medium | absolute pinned values | patch: `BOOKING_CHANGED` against pinned "before" |
| Spec review: quantity and note bounds live in the route schema only | medium | `schemas/preorder.py:9-14` | patch: argument constraints |
| Spec review: an omitted note erases the current one | medium | `preorder_service.py:94` | patch: omitted keeps the note |
| Spec review: the booking and removed-quantity card fields have no source | low | services return carts only | patch: named reads |
| Spec review: money format in `result` unstated | low | `usd()` | patch |
| Spec review: doc lacks result shapes; "Cancel booking" next to the "Cancel" button | low | doc lines 124-132 | patch: shapes, codes, "Yes, cancel it" |
| Spec review: joined bookings listed but not editable | medium | owner-only services | patch: prompt rule on `role` |
| Spec review: several appliers per file | low | backend.md one class per file | patch: one file each |
| Spec review: pre-order test helpers are local to one module | medium | `test_preorder.py:77-212` | patch: move first |
| Spec review: README lines | low | lines 31, 32, 143 | patch |
| Spec review: missing matrix rows | medium | | patch: rows added |

## Design Notes

**Dry runs are sound for every action.** `BookingService.cancel` and `edit` have no notifier and their routes add no background work; `PreorderService.set_item`, `remove_item` and `submit` only flush. Nothing outside the database runs, so a rolled-back session leaves no trace (checked in the spec review, 2026-11-18).

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

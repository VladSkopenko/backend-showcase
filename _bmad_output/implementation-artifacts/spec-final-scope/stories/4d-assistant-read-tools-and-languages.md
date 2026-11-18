---
title: 'Assistant: read tools and languages'
type: 'feature'
created: '2026-11-18'
status: 'draft'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/assistant.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/stories/4b-assistant-streamed-turn.md'
  - '{project-root}/docs/adr/0020-assistant-composes-ai-tools.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After 4b the assistant knows the menu and nothing else: not where the restaurant is, whether a table is free, nor the user's own bookings and pre-order.

**Approach:** Four more read tools in three `ai_tools` packages over the existing services, the restaurant's rules as prompt facts from settings, and the live check in English, Ukrainian and Russian (CAP-5, CAP-8).

## Boundaries & Constraints

**Always:**
- Tools: `list_locations()` (`id`, `address`, `description`, `table_count`); `find_tables(date, party_size, location_id?, time?)` through `TableSearchService.search` with `limit=50`, `offset=0`, each table as `id`, `label`, `capacity`, `location {id, address}` and `free_starts` (the free start times only, restaurant-local `HH:MM`), with `total`; `list_my_bookings()` from `BookingService.list_for_user`: the bookings with `ends_at > now` in every status soonest first, then the latest 10 of the rest, each as `id`, `status`, `starts_at`, `ends_at`, `party_size`, `table {label, capacity}`, `location {address}`, `role`, `participants` (names and roles); `get_my_preorder(booking_id)` from `PreorderService.get_cart` and `get_my_preorder` with `guest_token=None`: `cart {items [{dish_id, name, quantity, note, price, line_total, is_available}], total}` and `submitted_parts [{submitted_at, items, total}]`. Slicing and picking fields is result shaping, not a rule.
- The user's identity comes only from the tool context; a booking the user has not joined answers `{"error":"BOOKING_NOT_FOUND",…}` to the model, as the routes answer 404.
- Prompt facts from `BookingSettings`, never through tools: the slot grid (first slot, last slot, step), the stay length and the longest stay, the closing time, the instant and the request party sizes, the horizon, the cancel cutoff, the pre-order lock, the timezone; dates and times in tool arguments and results are restaurant-local ISO strings.
- The system prompt also says: for "how busy" questions call `find_tables` and read the free starts across tables; do not invent dishes, tables or bookings; the model replies in the language of the user's message.
- `AiToolContext` gains `booking: BookingSettings` and `max_item_quantity`; every tool opens its own session per call and builds the services exactly as the feature's `endpoints/dependencies.py` does.

**Never:** Tools for notifications, the invite link or the owner's group view; free-text menu search; write tools (5); changing any service, route or event; translations.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Locations | fake model calls `list_locations` | both seeded locations with their table counts, oldest first | N/A |
| Free tables | one booking on the four-seat table at 13:00 tomorrow; `find_tables(tomorrow, 4)` | that table lists the starts outside 11:30 to 14:30, the other four-seat table every start; six-seat tables absent | N/A |
| Busy evening | `find_tables(tomorrow, 2, time="19:00")` with that start booked everywhere | `tables` empty, `total` 0 | N/A |
| Bad arguments | `find_tables` with `party_size` "four" | an error tool message naming the field; no `error` event | N/A |
| Domain error | `find_tables` for a date past the horizon | `{"error":"DATE_OUT_OF_RANGE",…}`; the turn goes on | N/A |
| My bookings | the user owns a past booking, a cancelled upcoming one and has joined a confirmed one; 12 past bookings in all | the two upcoming soonest first, then 10 past, with role and participants | N/A |
| My pre-order | a cart with two lines and one submitted part | both blocks with live prices and totals | N/A |
| Own data only | `get_my_preorder` for a booking the user has not joined | `{"error":"BOOKING_NOT_FOUND",…}` | N/A |
| Prompt facts | any turn | the fake received the grid 10:00 to 21:30 by 30 min, the 90-minute stay, party sizes 4 and 8, the horizon, the cutoff, the lock and the timezone from the test settings | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/common/ai_tools.py` -- the two new context fields.
- `backend/src/app/features/core/locations/ai_tools/`, `core/bookings/ai_tools/`, `preorder/ai_tools/` -- `LocationTools`, `BookingTools`, `PreorderTools` as `MenuTools` in 4b; services built as in `locations/endpoints/dependencies.py`, `bookings/endpoints/dependencies.py:20-35`, `preorder/endpoints/dependencies.py:16-28` (`PreorderService` needs `ParticipantService`, `DishCatalogService`, `max_item_quantity`, `timezone`).
- `backend/src/app/features/core/bookings/services/table_search_service.py:28-70` -- the search; `booking_service.py:102` -- `list_for_user` ordered `starts_at desc` (`booking_repository.py:74-86`), the tool reorders; `preorder/services/preorder_service.py:50-56,146-155` -- the two reads; `core/locations/services/location_catalog_service.py:16` -- unchanged, all of them.
- `backend/src/app/features/assistant/services/toolkit_builder.py`, `system_prompt_builder.py` -- the three packages and the facts block from `BookingSettings`.
- `backend/tests/test_assistant_tools.py` -- the matrix with the booking fixtures (`tests/support/booking_fixtures.py`: `venue`, `users`, `fake_clock`; `tests/support/bookings.py` constants) and the fake model scripting each call.
- `docs/roadmap.md`, `README.md:32,142`, `README.uk.md` -- tick "AI assistant: a chat with streamed answers and read tools"; the "What is next" sentence goes after story 5.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/tests/test_assistant_tools.py` -- one test per matrix row, written first and failing -- contract.
- [ ] Context fields, the three `ai_tools` packages, the toolkit and prompt builders -- behaviour.
- [ ] `docs/roadmap.md`, `README.md`, `README.uk.md` -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean.
- Given the local API with Vlad's key, when a verified user asks in English, Ukrainian and Russian where the restaurant is, how busy Friday evening is, whether a table for four is free at 19:00, what their bookings are and what is in their cart, then every answer is in the language of the question and carries the facts the routes return for the same questions; a question about another person's booking gets no data.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Spec review: `list_my_bookings` shaping looks like a copied rule; "upcoming" undefined | low | `booking_repository.py:74-86` orders `starts_at desc` | patch: `ends_at > now`, shaping allowed |
| Spec review: `find_tables` does not say `limit`, `offset` | medium | `table_search_service.py:28-37` | patch |
| Spec review: tool context fields unnamed; the preorder tool needs five | medium | `preorder/endpoints/dependencies.py:16-28` | patch: fields named |

## Design Notes

**What users ask, and the tool for it.** "Where are you, how many tables, what is the place like" → `list_locations`; "is there a table for four on Friday at seven, how busy are you Friday evening" → `find_tables` (busy = few free starts across tables); "when is my reservation, who is coming" → `list_my_bookings`; "what did I pre-order, what is in my cart" → `get_my_preorder` (the draft and the submitted parts together, as people do not separate them). Opening hours and the booking rules are prompt facts. Not tools: notifications ("was my request approved" is the booking status), the invite link (the page has it), the owner's group view (nobody asked; story 5 may revisit).

**Tool result example** for `find_tables`: `{"tables":[{"id":"…","label":"Table 2","capacity":4,"location":{"id":"…","address":"Old Town Square"},"free_starts":["18:00","18:30","20:30"]}],"total":3}`.

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

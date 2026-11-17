---
title: 'Group pre-order for the booking owner'
type: 'feature'
created: '2026-11-17'
status: 'in-review'
baseline_commit: '096445269a1aae2bdc8d03bfec8ad953c10d6ae5'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/docs/adr/0016-booking-participants-and-guest-identity.md'
  - '{project-root}/docs/adr/0017-preorder-parts-per-participant.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The owner of a booking sees only their own submitted pre-order; the frontend's "Group Pre-Order" modal waits for an API with the guests' blocks and the "Pre-orders N/M" counter.

**Approach:** One new read route, `GET /bookings/{booking_id}/group-pre-order`, answers the owner with every participant of the booking and each participant's submitted parts, totals per participant and a grand total. Nothing else changes: each participant still submits only their own part.

## Boundaries & Constraints

**Always:**
- Only the booking owner reads it. A signed-in caller who is not the owner gets 404 `BOOKING_NOT_FOUND`, as cancel and edit answer; a caller without a valid access cookie gets 401 `NOT_AUTHENTICATED`, a guest with only the `guest_token` cookie included.
- Every participant appears, owner first, then guests in join order, each with `id`, `name`, `role` as in `Booking.participants`, their submitted parts oldest first, and `total_cents`. A participant with nothing submitted appears with `parts: []` and `total_cents: 0`.
- Parts and lines have the same shape and the same live menu data as `GET /my-pre-order`: a dish made unavailable after submit stays with `is_available: false` and counts in the totals. Drafts never appear.
- Readable in every booking status (`CONFIRMED`, `PENDING`, `REJECTED`, `CANCELLED`) and after the pre-order window; no inactive-booking check, no row locks.
- Pre-order stays a regular feature that imports only core (ADR 11): core bookings answers the owner check and the named participants.

**Never:** Owner final submit, editing or removing others' lines, Remove Guest, statuses Sent/Confirmed/Rejected, any change to existing routes or response shapes, a migration.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Whole group | owner with 2 parts, joined user with 1 part, guest without an account with 1 part | three participants in order, parts oldest first, per-participant totals, grand total = their sum | N/A |
| Not yet ordered | a joined guest has only a draft | listed with `parts: []`, `total_cents: 0`; draft lines absent | N/A |
| Live menu data | a dish's price changes, another becomes unavailable, after submit | new price in lines and totals; the unavailable line stays with `is_available: false` and counts | N/A |
| Pending request | `PENDING` booking with a joined guest | 200, both listed with `parts: []` | N/A |
| Inactive booking | `REJECTED` or `CANCELLED` booking | 200, the group as it was | N/A |
| Joined user asks | signed-in GUEST participant | nothing | 404 `BOOKING_NOT_FOUND` |
| Cookie guest asks | only the `guest_token` cookie | nothing | 401 `NOT_AUTHENTICATED` |
| Stranger or unknown id | signed-in user not in the booking, or no such booking | nothing | 404 `BOOKING_NOT_FOUND` |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/bookings/services/participant_service.py` -- new owner-only read returning the booking's named participants: `BookingRepository.get_for_user` without `for_update`, and no `InactiveBookingGuard` (unlike `lock_owned`, which would answer 409 for `REJECTED`).
- `backend/src/app/features/core/bookings/repositories/booking_participant_repository.py:41` -- `list_named` already orders owner first, then join time; reuse it.
- `backend/src/app/features/core/bookings/dto/participant_view.py` -- `ParticipantView(id, name, role)`, reuse.
- `backend/src/app/features/preorder/services/preorder_service.py` -- new `get_group_preorder`; the grouping of `get_my_preorder` into parts moves into one private helper used by both.
- `backend/src/app/features/preorder/repositories/preorder_item_repository.py:26` -- submitted items for many participants at once, same ordering as `list_submitted`.
- `backend/src/app/features/preorder/dto/`, `schemas/preorder.py` -- new group and per-participant views and responses; parts reuse `SubmittedPartView`/`SubmittedPartResponse`.
- `backend/src/app/features/preorder/endpoints/preorder.py` -- the route with `CurrentUserDep` and `error_responses`; its description names the `guest_token` cookie as refused.
- `backend/src/app/features/preorder/endpoints/openapi_tags.py:11` -- "Each participant sees only their own items" becomes untrue; add that the owner also sees the whole group.
- `backend/tests/test_openapi.py:50` -- add the route to `FLOWS["Pre-order"]`; `test_guest_routes_mention_the_guest_cookie` then requires `guest_token` in its description.
- `backend/tests/test_preorder.py:77-235` -- fixtures and helpers (`menu`, `make_dish`, `add_party`, `fill`, `submit`, `my_preorder`, `make_unavailable`); the new tests go in this file, since test modules may not import each other (`tests/test_suite_layout.py`).
- Do not change: `/cart*`, `/my-pre-order`, booking routes and their schemas.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_preorder.py`, `backend/tests/test_openapi.py` -- one test per matrix row and the flow entry, written first and failing -- contract.
- [x] Core bookings owner read, preorder repository, service, DTOs, schemas, route, tag text -- behaviour.
- [x] `docs/adr/0017-preorder-parts-per-participant.md` -- Status "Amended 2026-11-17": the owner sees the whole group through this route; the owner send, Remove Guest with its lock rule and the price fixed at send are dropped (final scope), so prices stay live; Context updated -- record.
- [x] `docs/adr/0016-booking-participants-and-guest-identity.md` -- Status amended: removing a guest and leaving a booking are dropped, not coming with the group pre-order -- record.
- [x] `docs/roadmap.md`, `README.md`, `README.uk.md` -- tick the group pre-order; add it to the API row; drop it from "What is next" -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean.
- Given the local API with `APP_ENVIRONMENT=local` (codes come back as `debug_code`), when an owner books, a second registered user and a cookie guest join through `GET /bookings/{id}/invite` and `POST /invites/{code}/join`, and each submits a part, then the owner's call lists all three with totals that add up, the second user gets 404 and the cookie guest 401.
- Given dev after deploy, when the route is called without a session, then it answers 401, so the route is live.

## Design Notes

Response, flat participant fields so the frontend's `Participant` type fits:

```json
{"participants": [
  {"id": "…", "name": "Anna", "role": "OWNER", "parts": [{"id": "…", "submitted_at": "…", "items": [], "total_cents": 2400}], "total_cents": 2400},
  {"id": "…", "name": "Max", "role": "GUEST", "parts": [], "total_cents": 0}],
 "total_cents": 2400}
```

"Pre-orders N/M": N is the participants with non-empty `parts`; M is the frontend's choice between the participant count and `party_size`, both already in its data. The owner's reservation card needs this call to show the counter; guests keep `my-pre-order`.

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

## Implementation Notes

- `ParticipantService.list_for_owner` reads `get_for_user` without a lock or guard and maps `list_named` to `ParticipantView`.
- `PreorderItemRepository.list_submitted` now takes `participant_ids`; `get_my_preorder` passes one id, so one query serves both reads.
- `ParticipantPreorderResponse` extends core bookings' `ParticipantResponse` (precedent: invites schemas import core booking schemas), so the flat `id`, `name`, `role` stay identical to `Booking.participants`.
- ADR 17 Alternatives were touched too: the price-snapshot reason no longer cites the owner send, and the lock alternative no longer cites owner group actions.
- Live check (2026-11-17, local API at revision 0019, which lacks only the dev bot data and the Grafana role): owner 200 with Anna 5900 (two parts), Boris 1800, Clara 3600, total 11300 equal to the sum and to each `my-pre-order`; Boris 404 `BOOKING_NOT_FOUND`; cookie guest and no session 401 `NOT_AUTHENTICATED`. The dev smoke check waits for the deploy.
- 2026-11-17, parent session after the code review patches: 746 tests, ruff, format check, mypy and 10 import contracts clean. The live check script was re-run on a fresh local API by the parent with the same result (Anna 5900 in two parts, Boris 1800, Clara 3600, total 11300; Boris 404, cookie guest and no session 401). Local `app` now holds four `live-*@example.com` users with two bookings from the two runs. During the patches the implementation subagent tried to run `ruff format`, which writes files; the permission system refused it and nothing ran.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Access bullet (404 for cookie guest) contradicts the matrix (401) | high | `CurrentUserDep` answers 401 before the service runs | patch: bullet rewritten |
| `test_openapi.py` flows and the guest-cookie description test not planned | high | `test_openapi.py:50`, `:94-129` | patch: task and Code Map |
| Pre-order tag text becomes false | medium | `openapi_tags.py:11` | patch |
| New test file cannot import the helpers | medium | `tests/test_suite_layout.py` | patch: tests in `test_preorder.py` |
| Dev acceptance unverifiable (no joined bot bookings, bot password in n8n) | medium | n8n never calls invites | patch: local live check, dev smoke 401 |
| ADR 16 and 17 amendments, roadmap and README incomplete | medium | ADR 16 Consequences, ADR 17 Context and lock bullet | patch |
| PENDING, REJECTED and unavailable-dish cases unpinned | medium | `InactiveBookingGuard` answers 409 | patch: matrix rows |
| "N/M" undefined | low | Figma 4/4 | patch: design note |
| `baseline_commit` not in the local repository | low | merge commit exists only on the remote; local is not fetched | patch: local HEAD with the same tree |
| Code review: tag text reads as if the window limits the group read (blind) | low | `openapi_tags.py:12` | patch: window limits cart writes and submit, reads stay open |
| Code review: ADR 17 first Decision bullet omits the owner check and named participants (blind) | low | ADR 17 line 30 | patch |
| Code review: README ADR 17 index rows omit the group view (blind) | low | `README.md:104`, `README.uk.md:104` | patch |
| Code review: ADR 16 does not say a rejoined guest's old participant stays in the group view (blind) | low | ADR 16 Consequences | patch: one clause |
| Code review: participant order and grouping not pinned against submission order (blind) | medium | the whole-group test submits in join order | patch: interleaved-submit test |
| Code review: no test that another booking's parts of the same person are excluded (blind) | low | every test used one booking | patch: Grace submits in a second booking |
| Code review: `Group.max` shadows the builtin and holds a token (blind) | low | test helper | patch: `max_token` |
| Code review: DTO copies participant fields while the schema inherits core's response (blind) | low | a drifted shape fails `model_validate` in the tests; no other harm named | rejected |
| Code review: owner check joins the table row it discards (blind) | low | one extra join on a small read | rejected |
| Code review: edge-case hunter and verification-gap layers | false | both returned no findings | none |

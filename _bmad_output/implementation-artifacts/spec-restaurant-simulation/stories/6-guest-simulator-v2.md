---
title: 'Guest simulator v2'
type: 'feature'
created: '2026-11-13'
status: 'done'
baseline_commit: '10d1fe71c8475cbc9088c48c14fe8025abaccbee'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/patterns.md'
  - '{project-root}/docs/adr/0014-booking-simulator-on-dev.md'
  - '{project-root}/n8n/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The n8n simulator books uniformly at random with four bots, never orders food and never asks for a large table, so the dev data has no patterns worth a dashboard.

**Approach:** Rewrite `n8n/workflows/booking-simulator.json` so each run plays one of the 40 bots with the weights of `patterns.md`: when they book, how many people, large-party requests, pre-orders and cancellations. Vlad imports the file once over the current workflow.

## Boundaries & Constraints

**Always:**
- Same workflow id (`BookingSimul8tor`), same credential (`Booking bot password`), sign-in per run as today; schedule every 2 minutes; timezone Asia/Tbilisi.
- `apiBaseUrl` = `https://backend-showcase-dev.duckdns.org/api/v1` in the file; only the public dev API (ADR 14).
- Every weight from `patterns.md` lives in one `CONFIG` object at the top of the first Code node; nothing else holds a number that tunes behaviour.
- Personas: bots 1 to 10 are regulars (half of the runs; 80% at a favourite location; two favourite dishes), 11 to 40 occasional; favourites come from a stable hash of the bot number or location id, so no state is kept.
- Each run: about 15% cancel one of the bot's own future `CONFIRMED` or `PENDING` bookings more than 30 minutes away; otherwise book. Before that, with a configured chance, the bot pre-orders for one of its own approved large bookings (confirmed, party above 4) that still has no submitted part.
- Booking: date by the lead-time weights, start by the hour and weekday weights, party by the day table incl. holidays (14 Feb, 8 Mar, 31 Dec). A party of 1 to 4 books instantly and keeps the rule "at least 4 fitting tables free at that start"; a party of 5 to 8 sends a request, only for starts more than 2 hours ahead (the API refuses closer ones), without the 4-tables rule (requests hold no table).
- Pre-order after a 201 `CONFIRMED`, only when the start is more than 30 minutes away: per person a main course 90%, appetizer 50%, dessert 40% (lunch and dinner adjustments), dishes weighted by location and regular favourites, available dishes only; `PUT` each item, then `POST` submit.
- Expected API refusals end the run quietly (409 slot taken, overlapping booking, too late, pre-order closed); any other status fails the execution so a broken simulator shows up in n8n.
- `n8n/README.md` describes the new behaviour, the import steps and the `CONFIG` object.

**Never:** Staff actions (story 7), invites between bots, generating past data, calls to staging or prod, changes to the backend.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Instant booking | weekday, party 2, slot with 4+ free tables | 201 `CONFIRMED`, then a submitted pre-order | N/A |
| Large request | Saturday, party 7, start 3 days ahead | 201 `PENDING`, no pre-order | N/A |
| Too close | party 6, start within 2 hours | no request sent | N/A |
| No room | fewer than 4 fitting free tables at every candidate start | run ends without booking | N/A |
| Cancel run | bot has a booking more than 30 min away | 200 `CANCELLED` | N/A |
| Approved pre-order | bot has an approved large booking without parts | items added, part submitted | N/A |
| Race | 409 on book, cart or submit | run ends quietly | N/A |
| Broken API | 500 or 401 | execution fails | n8n marks the run failed |

</frozen-after-approval>

## Code Map

- `n8n/workflows/booking-simulator.json` -- today: Every 5 minutes → Plan the visit (Code) → Log in → Keep the session → Book/Cancel branches with Search tables, Pick a free slot, Book, List my bookings, Pick a booking to cancel, Cancel, Check answers. Keep the sign-in and cookie handling; extend the plan, add request, pre-order and approved-pre-order paths.
- API used (dev, public): `POST /auth/login`; `GET /bookings/tables?date&party_size&time&location_id&limit`; `POST /bookings`; `GET /bookings`; `POST /bookings/{id}/cancel`; `GET /menu/dishes?limit=50` (fields `id`, `category`, `price_cents`, `is_available`); `PUT /bookings/{id}/cart/items/{dish_id}` `{quantity, note}`; `POST /bookings/{id}/cart/submit`; `GET /bookings/{id}/my-pre-order` for submitted parts; `GET /locations` for ids.
- `n8n/README.md` -- behaviour table, bots section, import steps.
- `n8n/compose.yml` -- local n8n for trying the workflow (API URL edited locally only).

## Tasks & Acceptance

**Execution:**
- [x] `n8n/workflows/booking-simulator.json` -- rewrite per the constraints -- behaviour.
- [x] A Node script under `n8n/` (or a test in the workflow's Code nodes run by `node`) that loads `CONFIG` and the planning functions from the JSON and checks over 10 000 simulated plans: persona split, lead-time, hour and party-size shares within a few points of `patterns.md`, holiday overrides, no request within 2 hours -- verification of the weights without the API.
- [x] `n8n/README.md` -- behaviour, import steps, `CONFIG` -- docs.

**Acceptance Criteria:**
- Given the workflow file, when the plan check runs, then every share is within tolerance of `patterns.md`.
- Given Vlad imported the file on the dev n8n, when it has run for an hour, then bots beyond 1 to 4 have bookings, some pending requests exist, and confirmed bookings carry submitted pre-orders (checked through the API as a few bots).

## Implementation Notes

- 2026-11-13: workflow rewritten (34 nodes, branches chained explicitly), plan check with seeded PRNG and node harness; numbers patterns.md left open are now recorded there (start weights, Friday-Sunday weekend for party sizes, request split, meal windows, approved pre-order chance). Verified by the parent session: JSON valid; plan check passes with seed 7; six manual executions of the workflow in a throwaway n8n 2.47.7 against the dev API all succeeded: bots 26, 33 and 28 booked CONFIRMED and submitted pre-orders, bot 5 sent a PENDING request for 5 people, two cancel runs found nothing to cancel and ended quietly.
- 2026-11-14: Vlad imported the workflow on the platform n8n (it had none before; README import steps start from a new workflow). The hour check through the API as all 40 bots runs after the import.
## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route |
|---|---|---|
| Branch order depends on canvas positions (acceptance, blind) | medium | patch: explicit chain |
| Draft cart leftovers after a 409 (blind, edge-case) | medium | patch: skip the dish; skip approved bookings with a draft |
| Menu page not checked for completeness (blind, edge-case) | low | patch |
| Plan check: unseeded, local URL unguarded, requests never asserted sent, day weights / request split / approved chance unchecked, flat tolerance, only three nodes run (verification-gap, blind, acceptance) | medium | patch |
| README import steps need a VM shell (parent) | medium | patch: UI import |
| ADR 14 out of date (blind, verification-gap) | low | patch |
| Numbers not in patterns.md (acceptance, blind) | low | patterns.md updated by the parent session |
| Lead-time shares drift per weekday (acceptance) | low | accepted and recorded in patterns.md |
| Session rows grow without cleanup (blind) | low | defer |
| Plan check not in CI (verification-gap) | low | defer (CI is Vlad's) |

## Verification

**Commands:**
- `node n8n/<plan check script>` -- expected: all shares within tolerance
- `python3 -m json.tool n8n/workflows/booking-simulator.json` -- expected: valid JSON

**Manual checks (if no CLI):**
- Import on the dev n8n (Vlad), then sign in as a few bots through the API and read their bookings and pre-orders.

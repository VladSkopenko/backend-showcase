---
title: 'Waiter bot workflow'
type: 'feature'
created: '2026-11-14'
status: 'done'
baseline_commit: '63799301a1fe2b2120526102afafc6b5fe22d5f2'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/patterns.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/6-guest-simulator-v2.md'
  - '{project-root}/docs/adr/0014-booking-simulator-on-dev.md'
  - '{project-root}/n8n/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Large-party requests from the guest simulator stay `PENDING` until the 2-hour auto-reject, so the dev data has no staff decisions, no approved large bookings and nothing for the staff dashboard.

**Approach:** A second n8n workflow, `n8n/workflows/waiter-bot.json`, signs in as `waiter-bot@example.com` and decides pending requests through the staff API like a busy waiter, by the waiter weights of `patterns.md`. Vlad imports it through the editor.

## Boundaries & Constraints

**Always:**
- Workflow id `WaiterBotDecides`, name `Waiter bot`; schedule every 5 minutes; timezone Asia/Tbilisi; credential `Booking bot password` (the waiter has the same password hash, migration 0018); `apiBaseUrl` = `https://backend-showcase-dev.duckdns.org/api/v1` (ADR 14).
- Every weight lives in one `CONFIG` object at the top of the first Code node: skip chance 0.4, approve chance 0.8, far threshold 3 days, far deferral chance 0.5, page size 50.
- A skipped run ends before signing in (no session row).
- One page per run: `GET /staff/booking-requests?limit=50`, in the API's order (earliest start, then oldest request); the rest waits for later runs.
- Per request, in that order: if its start is more than 3 days away, leave it with chance 0.5; otherwise approve with chance 0.8, else reject. Approving the earliest request rejects its competitors on the API side, which is how the waiter prefers the earliest.
- Approve answering 409 `SLOT_UNAVAILABLE` (table already confirmed) is followed by a reject of that request. 409 `REQUEST_NOT_PENDING` or `REQUEST_EXPIRED` skips the request quietly (a competitor's approval or the auto-reject got there first). The run continues with the next request after any of these.
- Any other non-2xx (401, 403, 500, a failed sign-in) fails the execution.
- `n8n/README.md` documents the workflow, the `CONFIG` object and the import steps; ADR 14 records the waiter workflow.

**Never:** Changes to the backend or to the guest simulator; acting on staging or prod; state kept between runs.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Skipped run | random below 0.4 | no sign-in, no calls | N/A |
| No requests | empty page | run ends after the list | N/A |
| Near request | start in 1 day | approved (80%) or rejected (20%) | N/A |
| Far request | start in 5 days | left (50%), else decided as above | N/A |
| Competing | two requests, same table and time | the earlier one decided first; if approved, the later one answers `REQUEST_NOT_PENDING` and is skipped | N/A |
| Table taken | approve answers 409 `SLOT_UNAVAILABLE` | request rejected | N/A |
| Expired | approve answers 409 `REQUEST_EXPIRED` | skipped | N/A |
| Broken API | 500 or 401 | execution fails | n8n marks the run failed |

</frozen-after-approval>

## Code Map

- `n8n/workflows/booking-simulator.json` (story 6) -- the pattern to copy: Schedule Trigger with timezone, `Plan the visit` Code node with `CONFIG` on top, `Log in` HTTP node with `httpCustomAuth` credential `BookingBotPasswd` and `neverError` + full response, `Keep the session` cookie handling, `Check ...` Code nodes that end quietly on expected 409 codes and throw otherwise.
- Staff API (`backend/src/app/features/core/bookings/endpoints/booking_requests.py`): `GET /staff/booking-requests?limit&offset` → `{items:[{id,status,owner_first_name,party_size,starts_at,ends_at,created_at,table,location,competing_requests}],total,limit,offset}`, only requests starting beyond the lead; `POST /staff/booking-requests/{id}/approve` and `/reject` → the request view. Errors: 403 `STAFF_ONLY`, 404 `BOOKING_NOT_FOUND`, 409 `REQUEST_NOT_PENDING`, `REQUEST_EXPIRED`, `SLOT_UNAVAILABLE` (`endpoints/errors.py`).
- `n8n/check-simulator-plan.mjs` -- the pattern for a plan check: loads Code nodes from the JSON with `node:vm`, seeded mulberry32, binomial tolerance, harnesses for decision nodes. Do not change it.
- `n8n/README.md` -- add a waiter section next to the simulator one (behaviour, `CONFIG`, import as a new workflow).
- `docs/adr/0014-booking-simulator-on-dev.md` -- amend: the waiter workflow decides requests on dev.

## Tasks & Acceptance

**Execution:**
- [x] `n8n/check-waiter-plan.mjs` -- new, written first: loads the waiter's Code nodes from the JSON, checks over seeded simulated runs the skip share, approve share, far deferral share and the threshold boundary, and runs the decision/answer Code nodes on stub API answers for each matrix row; guards that `apiBaseUrl` is the dev URL -- verification without the API.
- [x] `n8n/workflows/waiter-bot.json` -- the workflow per the constraints -- behaviour.
- [x] `n8n/README.md`, `docs/adr/0014-booking-simulator-on-dev.md` -- docs.

**Acceptance Criteria:**
- Given the workflow file, when `cd n8n && npm test` runs (the check moved to `n8n/tests/waiter-bot.test.mjs`), then every share is within tolerance of `patterns.md` and every matrix row behaves as listed.
- Given Vlad imported both workflows on the dev n8n, when they have run for an hour, then bots' large requests show `CONFIRMED` and `REJECTED` decisions (checked through the API as the bots), and an approved request later carries a submitted pre-order from the guest simulator.
- Done 2026-11-14 with Vlad's screenshots in `docs/images/`. Follow-up, not blocking: once both workflows run, Vlad takes editor screenshots and an n8n row goes into `README.md` and `README.uk.md` (tailnet-only editor link, links to both workflow JSON files, screenshots).

## Implementation Notes

- 2026-11-14: the waiter goes through the page with a Loop Over Items node (v3, batch size 1): an HTTP Request node sends the calls of all its items at once (`Promise.allSettled` in n8n 2.47), so competing requests would race instead of the earliest being decided first. Every fork ends in two Code gates of which exactly one passes, and every path returns to the loop. The check script emulates the Code, HTTP and Loop Over Items nodes along the JSON's connections against a stub staff API; mutations (a missing loop-back, `>=` at the threshold, a quiet `SLOT_UNAVAILABLE`, batch size 2, approve chance 0.7) each fail it. A throwaway n8n 2.47.7 ran the workflow (with a manual trigger added, skip 0 and approve 1, against a local stub, since the bot password is not available to the dev session): 6 requests in API order, the competitor answered `REQUEST_NOT_PENDING` and was skipped, `SLOT_UNAVAILABLE` was followed by a reject, `REQUEST_EXPIRED` was skipped, the far request was left, the loop reached `done` and the execution succeeded; a 500 on approve failed the execution. Not yet run against the dev API.

- 2026-11-14, parent session: plan check passes; review triage below (Vlad: no changes). Live: five manual executions in a throwaway n8n 2.47.7 against the dev API: one skipped, one decided all six pending requests (each answered 200), three found an empty page and ended quietly. Story 6 hour check through the API as the 40 bots: 38 new bookings by 30 bots, 32 of 35 new confirmed bookings with a submitted pre-order, bot 5's request approved by the waiter run.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route |
|---|---|---|
| Far deferral never lets a request reach the 2-hour auto-reject; docs claim some do (blind) | low | rejected by Vlad: no effect on the showcase |
| Far competitors: an earlier left request can lose to a later approved one (blind, edge-case) | low | rejected by Vlad |
| Waiter decides every pending request on dev, also ones made by hand (blind) | low | rejected by Vlad |
| Plan check ignores node settings (onError, disabled, executionOrder) (verification-gap) | low | rejected by Vlad |
| Broken-API rows accept any thrown error; CONFIG only checked statistically; NaN seed; stub competes on equal start only (blind, edge-case) | low | rejected by Vlad |
| REQUEST_EXPIRED in Check the rejection is unreachable (blind) | low | rejected: harmless |
| A request failing every run blocks the rest of the page (edge-case) | false | the spec wants other statuses to fail the run |
| Sessions from login without logout (blind) | low | already in deferred-work (session rows growth) |
| Plan check not in CI (verification-gap) | low | already in deferred-work |

## Verification

**Commands:**
- `cd n8n && npm test` -- expected: all tests pass
- `python3 -m json.tool n8n/workflows/waiter-bot.json` -- expected: valid JSON

**Manual checks (if no CLI):**
- Manual executions in a throwaway n8n 2.47.7 against dev before handing over; after Vlad's import, the hour check as the bots.

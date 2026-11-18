---
title: 'Assistant: confirmed actions and booking a table'
type: 'feature'
created: '2026-11-18'
status: 'done'
baseline_commit: '8e8e89cf2dbd93b00b8ab3fd9fcf3441018ae33b'
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

**Problem:** The assistant finds a free table but cannot book it; the guest has to leave the chat for the booking page.

**Approach:** The confirmation mechanism of `assistant.md`: a write tool proposes, a pending action holds the proposal, the guest applies or cancels a card. One action now, booking a table, plus the card in the frontend task document. Editing and cancelling a booking, the cart and submitting a pre-order part follow in story 5b on the same mechanism.

## Boundaries & Constraints

**Always:**
- **An action is one module per domain, next to its tool.** `core/bookings/ai_tools` owns `create_booking` (propose) and its applier (apply); `ToolkitBuilder` exposes the tools and a `kind -> applier` registry; the assistant only composes. ADR 20 is amended to say so.
- **Propose never writes.** `create_booking(table_id, date, time, party_size)` builds `starts_at` with `BookingSchedule.start_at` and runs `BookingService.create` in its own session that is always rolled back, never committed, also after a `DomainError` or an `IntegrityError` (a dry run). A `DomainError` reaches the model as `{"error": code, "message"}` and makes no card. Success fills the turn's proposal sink and answers `{"status": "awaiting_confirmation", "card"}`; the dry run's booking id is never shown or stored.
- **One proposal per turn, one pending card per session.** Only a successful proposal fills the sink; a later write call in the same turn answers `{"error": "ONE_PROPOSAL_PER_TURN"}`, a refused one leaves the sink empty, so the model may try another table. The turn stores the held proposal in its last transaction, after the assistant message is flushed, with the session row locked `FOR UPDATE`; storing sets the session's previous `PENDING` row to `CANCELLED`, or to `EXPIRED` when it is past `expires_at`. A turn that ends on the fallback text still stores and sends it; a turn that ends with `error` drops it.
- **Row `assistant_actions`:** `id`, `session_id` (FK, cascade), `message_id` (FK to the assistant message, cascade), `user_id` (FK, cascade), `kind` String(50) (`booking.create`), `payload` JSONB with pinned values (`table_id`, `starts_at` ISO with offset, `party_size`), `card` JSONB, `status` PostgreSQL enum `PENDING`, `APPLIED`, `CANCELLED`, `EXPIRED`, `FAILED` (uppercase, per backend.md), `result` and `error` JSONB, `created_at`, `expires_at` (`ASSISTANT_ACTION_TTL_HOURS`, default 24), `resolved_at`; a partial unique index on `session_id` where status is `PENDING` as a backstop.
- **Expiry is derived on read.** Everywhere an action is shown (the GET route, the session read-back, the `action` event, the model's history line), a `PENDING` row past `expires_at` reads as `EXPIRED`; refusing paths write nothing.
- **Card, English only:** `{title, fields: [{label, value}], notice, confirm_label}`. Booking: title "Book a table"; fields Location (address), Table ("Table 2, up to 4 guests"), Date (`%a, %d %b %Y`), Time ("19:00 – 20:30", en dash, restaurant-local), Guests; `notice` "Sent as a request; the restaurant confirms it." when the dry run's booking status is `PENDING`, else null; `confirm_label` "Book".
- **Action object** (event, routes, read-back): `{id, kind, status, card, created_at, expires_at, result, error}`; `result` of an applied booking `{booking_id, status}`; `error` `{code, message}`. The turn's stream sends `action` after the last `chunk` and before `done`. Each message in the session read-back carries `action` (object or null). The model's history appends `[Proposed booking.create: <status>]` to an assistant message with an action, plus the error code when `FAILED`.
- **Routes**, same access as the other assistant routes; an action not in the caller's session, or unknown, is 404 `ASSISTANT_ACTION_NOT_FOUND`:
  - `GET /assistant/sessions/{session_id}/actions/{action_id}` answers the object.
  - `POST …/cancel`: `PENDING` (not expired) becomes `CANCELLED`; an already `CANCELLED` one answers again; any other status is 409 `ASSISTANT_ACTION_NOT_PENDING`.
  - `POST …/apply` answers `text/event-stream`. Everything that decides the outcome finishes before the response is returned: the checks; then one transaction that claims the row with `UPDATE … SET status = 'APPLIED' WHERE id = … AND status = 'PENDING' AND expires_at > now`, runs the applier inside a SAVEPOINT on that same session, and commits; a `DomainError` rolls back to the savepoint, sets `FAILED` with `error`, and commits. A lost claim re-reads the row: `APPLIED` streams only `action` and `done` with `message_id` and `created_at` null; any other status is 409. The stream then sends `action` and a comment: `thinking`, `chunk`…, `done`, or `error` instead of `done` with the action unchanged, under the turn's time cap.
- **Applier contract:** an applier gets `ActionContext(session, user_id, payload)`, never opens its own session, runs the same service as the HTTP route (`BookingService.create` with the pinned payload and the JWT user) and returns `result`.
- **The comment** is the model with no tools bound, given the system prompt, the session's history window, and one human note that is not stored: "The guest pressed <confirm_label> on the card '<title>'. Outcome: <status>, <result or error>. Comment on it briefly in the guest's language." It is saved as an assistant message and its usage recorded. Apply ignores the per-minute cap; when `UsageLedger.is_budget_exhausted(now=)` (no lock, no raise) is true, the comment is fixed text with no model call: "Done: it is in your reservations." for `APPLIED`, "That did not work: <error.message>" for `FAILED`.
- **The system prompt:** booking a table is proposed with `create_booking` as soon as the guest has given the table, date, time and party size, without asking for confirmation in prose; the card is the confirmation; nothing is booked until the guest applies it; editing or cancelling a booking and changing the cart are not available yet, point to the website pages.
- **Settings:** `AssistantSettings.action_ttl_hours` (> 0) in `.env.example`.
- **Frontend task document:** the card section: the `action` event and object, card fields, statuses with how each looks (uppercase labels as the Figma file), the apply stream, cancel and GET, the errors, a pending card shown as expired once `expires_at` passes, no new bubble when a replayed `done` has a null `message_id`, scenarios; the Figma mockup named as shared separately.

**Never:** Other write actions (5b); editing values inside a card; card text in other languages; a second pending card per session; an apply that skips the domain checks; a write outside apply; per-user limits; changes outside `/api/v1/assistant`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Proposal | fake model calls `create_booking` for a free table, then answers | tool round, `chunk`…, `action` (PENDING, card as above), `done`; no booking exists; read-back has `action` on that message | N/A |
| Refused then retried | first call for a taken slot, second for a free table, same turn | first answers `SLOT_UNAVAILABLE`, second proposes; one action | N/A |
| Two proposals | two successful calls in one turn | second answers `ONE_PROPOSAL_PER_TURN`; one action | N/A |
| Newer card | a pending action, then a new proposal; and an expired pending, then a new one | old one `CANCELLED`; expired one `EXPIRED`; new `PENDING` | N/A |
| Fallback or error end | turn hits the round cap after proposing; turn fails with a provider error after proposing | fallback: action stored and sent; error: no action | N/A |
| Request party | party of 6 on a request table | card `notice` set; applied booking `PENDING` | N/A |
| Apply | apply a pending action | `action` (APPLIED, `result.booking_id`), `thinking`, `chunk`…, `done`; `GET /bookings` lists it; comment saved; the comment model got no tools | N/A |
| Apply fails | the slot is taken between proposal and apply | `action` (FAILED, `error.code` `SLOT_UNAVAILABLE`), comment, `done`; no booking | N/A |
| Comment fails | provider error during the comment after a successful apply | `action` (APPLIED), `error`; the booking stays | logged |
| Double apply | apply twice in a row | one booking; the second streams `action` (APPLIED) and `done` with null `message_id` | N/A |
| Cancel races apply | cancel commits first, then apply | apply 409 | 409 `ASSISTANT_ACTION_NOT_PENDING` |
| Not pending | apply a CANCELLED, FAILED or EXPIRED action; cancel an APPLIED one | nothing | 409 `ASSISTANT_ACTION_NOT_PENDING` |
| Expired | pending past `expires_at`: GET, read-back, apply | GET and read-back show `EXPIRED`; apply 409 | 409 |
| Cancel twice | cancel PENDING, then again | `CANCELLED` both times | N/A |
| Foreign or unknown | another user's action, or unknown, on GET, cancel, apply | nothing | 404 `ASSISTANT_ACTION_NOT_FOUND` |
| Budget exhausted at apply | today's spend at the budget | apply runs; fixed comment; no model call | N/A |
| History line | a session with an applied action, next turn | the model sees `[Proposed booking.create: APPLIED]` after that message | N/A |
| Access | unverified, guest cookie, no key | 403, 401, 503 on the three routes | as other assistant routes |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/assistant/models/assistant_action.py`, enum `AssistantActionStatus`, `migrations/versions/0024_create_assistant_actions.py` (`down_revision` "0023"), `model_registry.py` -- server-side `gen_random_uuid()` ids and FKs with `ondelete` as `models/assistant_message.py:23-26`; index `(session_id, status)`; partial unique index on `session_id` where `PENDING`.
- `backend/src/app/common/ai_tools.py` -- `AiToolContext` gains a mutable `ProposalSink` (one proposal: `kind`, `payload`, `card`), the `ActionContext` dataclass, an `ActionApplier` protocol, and a dry-run helper (a session that is always rolled back).
- `backend/src/app/features/core/bookings/ai_tools/booking_tools.py` -- `create_booking` and `BookingCreateApplier`; `BookingService` built as `core/bookings/endpoints/dependencies.py:26` does; `services/booking_service.py:49-101` unchanged (flushes, row locks, exclusion constraint mapped to `SlotUnavailableError`, no notifier, so a rollback undoes everything); `services/booking_schedule.py:46` `start_at`.
- `backend/src/app/features/assistant/services/` -- `ToolkitBuilder` also builds the registry; `AssistantActionService` (store with lock and supersede, get with derived expiry, cancel, claim, apply through the registry inside a savepoint); `AssistantTurnService` takes the sink, stores in `_finish`, yields `action`, adds history lines; an apply stream service for the comment; `UsageLedger.is_budget_exhausted`; `SystemPromptBuilder` rule.
- `backend/src/app/features/assistant/endpoints/` -- three routes (apply decides before returning `EventStreamResponse`, as `send_message` calls `turn.start` first at `assistant.py:157-158`), schemas for the object and card, errors, the descriptions of the messages route and the session detail gain `action`; the apply dependency builds its own `AiToolContext` and model instance.
- `docs/adr/0020-assistant-composes-ai-tools.md` -- amended: actions (propose and apply) live in the feature's `ai_tools`; the assistant composes tools and appliers.
- `backend/tests/test_assistant_actions.py` -- the matrix; the apply tests give the apply dependency its own fake model and assert it bound no tools. `test_assistant.py`, `test_settings.py`, `test_openapi.py` -- read-back field, key, routes.
- `docs/assistant-frontend-task.md` -- the card section.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_assistant_actions.py` and the pins in `test_assistant.py`, `test_settings.py`, `test_openapi.py` -- one test per matrix row, written first and failing -- contract.
- [x] Model, enum, migration 0024, registry, settings -- behaviour.
- [x] Shared contracts in `common/ai_tools.py`, `create_booking` and its applier, the action service, turn and apply streams, routes, schemas, prompt -- behaviour.
- [x] ADR 20 amendment, `docs/assistant-frontend-task.md` -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean.
- Given the local API with Vlad's key, when a verified user asks in Ukrainian for a free table for four on Friday evening and then to book the one at 19:00, then a card arrives with the table, time and guests; nothing is booked until Apply; after Apply the booking is in `GET /bookings` and the assistant comments in Ukrainian; a second Apply books nothing.

## Implementation Notes

- 2026-11-18: implemented by a subagent; shared contracts in `common/ai_tools.py` (`Proposal`, `ProposalSink`, `Card`, `CardField`, `ActionContext`, `ActionApplier`, `dry_run`), `create_booking` and `BookingCreateApplier` in `core/bookings/ai_tools`, the action service with a conditional supersede, the apply executor (claim, savepoint, FAILED, `UNKNOWN_ACTION`), the apply stream, `ModelCallRunner` pulled out of the turn service, `UsageLedger.is_budget_exhausted`, ADR 20 amended, the frontend task's card section. After the review patches 890 tests, ruff, format check, mypy (355 files) and 11 import contracts clean.
- 2026-11-18, live, parent session: local `app` migrated 0023 -> 0024, API on port 8010 with Vlad's key. A verified `live5a-…@example.com` asked in Ukrainian for a table for four on Friday evening; the assistant asked for the time; "Забронюй, будь ласка, столик на 19:00." streamed `thinking`, `chunk`, `action`, `done` with a PENDING card: Book a table, 48 Rustaveli Avenue, Table 4 up to 4 guests, Fri 20 Nov 2026, 19:00 – 20:30, 4 guests, notice null, confirm "Book"; no booking before Apply. Apply streamed `action` APPLIED with `result.booking_id` and status CONFIRMED and a Ukrainian comment; `GET /bookings` lists the CONFIRMED booking at Table 4 for 19:00. A second Apply streamed only `action` APPLIED and `done` with null `message_id` and `created_at`; still one booking. Before the prompt fix the same conversation never produced a card (see the triage row).

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Live check: the model kept asking for the time, the location and the table number and never proposed; once it passed a made-up `location_id` | high | three Ukrainian turns without a card | patch: pick a table itself and propose once date, time and party size are known; location ids only from tool results |
| Code review: a turn superseding a card can overwrite a card the apply just claimed (edge-case, blind) | high | unlocked read and unconditional status write in `store` | patch: conditional `UPDATE … WHERE status = 'PENDING'` |
| Code review: an unregistered `kind` gives 500 after the claim and the card stays PENDING (edge-case, blind) | medium | `self._appliers[action.kind]` | patch: FAILED `UNKNOWN_ACTION` |
| Code review: the card is an untyped dict (blind) | medium | 5b actions could break every session read | patch: `Card`, `CardField` in `common/ai_tools.py` |
| Code review: no index or uniqueness on `message_id`, none on `user_id` (blind) | low | read-back, history and cascade use them | patch |
| Code review: `action_ttl_hours` unbounded (edge-case) | low | timedelta overflow | patch: `le=720` |
| Code review: "yes, book it" in words proposes again (blind) | medium | the prompt has no rule for a pending card | patch: point to the button; table from `find_tables` |
| Code review: non-obvious decisions not recorded (blind) | low | workflow rule 5 | patch: ADR 20 |
| Code review: frontend doc stale handler count, no apply path, no 422 (blind) | low | doc text | patch |
| Code review: the savepoint path, the comment timeout, the empty comment and the cross-session 404 untested (verification-gap, blind) | medium | no test reaches them | patch: four tests |
| Code review: a failing second transaction after a committed apply gives 500 (edge-case) | low | only a database failure triggers it | rejected |
| Code review: a proposal stored next to the fallback text (edge-case) | false | the frozen block says a fallback end still stores and sends it | rejected |
| Code review: the TTL ignores the visit time (blind) | low | applying after the start fails cleanly with FAILED | rejected |
| Code review: no concurrency tests (blind) | low | the test fixture shares one connection; the claim and the conditional supersede are single statements | defer: deferred-work entry |
| Code review: the `action` event and the REST schema are built in two places (blind) | low | dto may not import schemas; a test compares them | rejected |
| Spec review: the applier in the assistant contradicts ADR 20 and cannot reach preorder in 5b | high | ADR 20 Alternatives; "Regular features are independent" | patch: applier next to the tool, registry from `ToolkitBuilder`, ADR amendment |
| Spec review: claim and write in one transaction need the caller's session | high | tools open their own sessions (`booking_tools.py:71,92`) | patch: `ActionContext(session, …)` |
| Spec review: a failed flush aborts the transaction, so FAILED cannot be written | high | `booking_service.py:85-90` | patch: savepoint |
| Spec review: an expiry write before a 409 is rolled back | medium | `database.py:44-50` | patch: expiry derived on read |
| Spec review: expiry readers and supersede status unstated | medium | three readers | patch |
| Spec review: claim ignores `expires_at`; lost claim replays a CANCELLED row | medium | check-then-claim gap | patch: `expires_at > now`, re-read |
| Spec review: 409 impossible inside the stream | high | `assistant.py:157-158` pattern | patch: decide before returning |
| Spec review: comment inputs unspecified | medium | Ukrainian acceptance | patch: prompt, history, unstored note |
| Spec review: apply-stream failures and timeout unstated | medium | turn error handling | patch: matrix row |
| Spec review: budget check at apply raises and locks | medium | `usage_ledger.py:54-76` | patch: `is_budget_exhausted`, verbatim texts |
| Spec review: replayed `done` shape and client behaviour | low | `assistant_event.py:29-30` | patch |
| Spec review: refused proposal and the per-turn limit | low | ambiguous | patch: only success fills the sink, renamed |
| Spec review: proposal on fallback and error ends | medium | `assistant_turn_service.py:139-188` | patch: rows |
| Spec review: concurrent turns can store two pending cards | medium | no lock in `_finish` | patch: `FOR UPDATE` and a partial unique index |
| Spec review: sink plumbing unstated | low | frozen context | patch |
| Spec review: naive `starts_at` | medium | `booking_schedule.py:46` | patch: `start_at`, ISO with offset |
| Spec review: notice re-derives a rule | low | the view has the status | patch: from the dry run's status |
| Spec review: card formats undefined | low | tests cannot pin values | patch |
| Spec review: FK targets and types unstated | low | existing models | patch |
| Spec review: status casing vs assistant.md | low | backend.md Data | patch: uppercase noted |
| Spec review: route descriptions not in the Code Map | low | `assistant.py:100-152` | patch |
| Spec review: dry-run soundness | false | no side effects outside the database | none; rollback stated |
| Spec review: fake model shared between turn and apply | low | `fake_chat_model.py:75-83` | patch: separate instance |

## Design Notes

**Dry run instead of a preview copy.** `BookingService.create` is the only place the booking rules live; running it in a session that is rolled back gives the proposal exactly the checks the apply will make, with nothing copied. It has no side effects outside the database (no notifier, no email).

**Action event example:**

```json
{"id":"…","kind":"booking.create","status":"PENDING","created_at":"…","expires_at":"…","result":null,"error":null,
 "card":{"title":"Book a table","confirm_label":"Book","notice":null,
   "fields":[{"label":"Location","value":"48 Rustaveli Avenue"},{"label":"Table","value":"Table 2, up to 4 guests"},
             {"label":"Date","value":"Fri, 20 Nov 2026"},{"label":"Time","value":"19:00 – 20:30"},{"label":"Guests","value":"4"}]}}
```

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

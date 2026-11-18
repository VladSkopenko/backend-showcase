# 20. The assistant composes the features' AI tools

Date: 2026-11-18

## Status

Accepted. Amends [ADR 11](0011-feature-sliced-backend-layout.md): a feature may keep a second
adapter, `ai_tools/`, beside `endpoints/`, and the assistant is the only feature that imports it.
Amended 2026-11-18 (story 5a): confirmed actions, propose and apply, live in the feature's
`ai_tools/` next to their tools. Amended 2026-11-18 (story 5b): stale cards fail on apply.

## Context

The AI assistant answers from the system's data through tools the model calls: the menu first,
then bookings, tables and the cart. A tool must call the same service the HTTP route calls and
copy no rule, and the user's identity must reach it from the verified JWT, never from a model
argument. [ADR 11](0011-feature-sliced-backend-layout.md) has no place for such code: a regular
feature may import only core features, so the assistant could not reach the cart's services, and
a tool that lived inside the assistant would have to know every feature's services and data
shapes. Putting the tools into `application_services` does not fit either: that package is for
work that spans features, while a tool is an adapter of one feature for one caller, the model.

## Decision

- **`ai_tools/` is a second adapter over `services`.** A feature that offers the model something
  keeps it in `ai_tools/` beside `endpoints/`. The package imports the feature's `services`,
  `dto` and `enums`, never directly `repositories`, `models`, `schemas` or anything from FastAPI;
  in the
  layers contract it sits on the same level as `endpoints`, independent of it. A tool is a
  `StructuredTool` over a coroutine with a Pydantic argument model whose every field is
  described; it opens its own session per call, builds the service as the feature's HTTP
  dependencies do, and shapes the service's result for the model, which is not a rule.
- **The assistant is the composition root.** Only `app.features.assistant` imports `ai_tools`
  packages, core or regular, and binds them to the model per request. Every feature may own an
  `ai_tools/`; nothing else may use it, so the HTTP routes and the tools stay two independent
  faces of one service.
- **The context is bound, not passed.** `app.common.ai_tools.AiToolContext` carries the user id
  from the JWT, the sessionmaker and the settings values the tools need. No tool argument names a
  user; the model cannot choose whose data a tool reads.
- **Actions live next to their tools.** A write the guest must confirm is one module per
  domain in the feature's `ai_tools/`: a propose tool that runs the route's service in a
  session that is always rolled back (a dry run) and hands a `Proposal` (kind, pinned payload,
  card) to the turn's `ProposalSink`, and an applier for that kind that runs the same service
  with the pinned payload in the `ActionContext` session it is given, never one of its own. The
  assistant stores the proposal as a pending action, claims it on apply and runs the applier
  inside a savepoint of its own transaction; `ToolkitBuilder` exposes the tools and a
  `kind -> applier` registry, so the assistant composes tools and appliers and knows no
  domain's services. `ProposalSink`, `Card`, `ActionContext` and the `ActionApplier` protocol
  live in `app.common.ai_tools`.
- **A card goes stale, not wrong.** An action whose card shows values the apply depends on pins
  a "before" snapshot of them in its payload: the booking's start, party size and length for an
  edit, the cart line's quantity and note (or no line) for a cart item, the draft lines and the
  total for a submit. The current state is compared with that snapshot inside the apply
  savepoint, under the same row locks the route's service takes: for an edit by
  `BookingService.edit(expected=…)` right after its locked re-read (user, table, booking), for the
  cart and the submit by the applier. A mismatch fails with a
  `*_CHANGED` domain error (`BOOKING_CHANGED`, `CART_CHANGED`), so a change made
  on the website after the card is never overwritten. Cancelling a booking and removing a cart
  line act on the identity of the booking or the line, not on values the guest saw, and are
  exempt.
- **Expiry is derived on read.** A pending action past `expires_at` is shown as `EXPIRED` by
  every reader (the action routes, the session read-back, the `action` event, the model's
  history line); the status is written only when a newer card supersedes it, so a refusing path
  writes nothing that a rollback would undo.
- **Apply decides before it streams.** The checks, the claim, the applier and the commit finish
  before the response starts, so a refusal (404, 409) is plain JSON; the stream carries only
  the outcome and the assistant's comment on it.
- **Apply ignores the per-minute cap.** The guest's press is not a new question; only the
  comment depends on the daily budget, and with the budget spent it is a fixed text.
- **The contracts enforce it.** `pyproject.toml` adds `ai_tools` to the layers, to the sources of
  the endpoint-level rules (no repositories or models, no schemas, no HTTP), exempts the
  assistant's imports of regular features' `ai_tools` from "Regular features are independent",
  and protects every `ai_tools` package so that only the assistant may import it.

## Alternatives considered

- **Tools inside the assistant feature.** One place to read, but the assistant would import every
  feature's services and dto, and a regular feature such as the cart would be unreachable under
  ADR 11 without a blanket exception.
- **Tools in `application_services`.** The package exists for cross-feature flows called by
  endpoints and background tasks; a tool over one feature's service is neither, and the services
  there would then depend on LangChain.
- **A tool router over tool groups.** Fewer tools bound per call, but another layer to design and
  test for a handful of tools; ruled out by the product scope.

## Consequences

- A new confirmed action is a propose tool and an applier in the feature that owns the rule,
  and one entry in that feature's `appliers()`; the assistant's action routes and storage stay
  unchanged.
- A new tool is a file in the feature it belongs to, next to the service it calls, and one line
  in the assistant's toolkit builder.
- The `ai_tools` packages depend on `langchain-core`; services, repositories and models do not.
- A feature's tools can change without touching its routes, and a route change leaves the
  tools alone, but a service change may break both, which the shared tests catch.
- A tool that needs two features' services has no home; it would be a cross-feature flow and
  belongs in `application_services` with a thin tool over it, which no story needs yet.

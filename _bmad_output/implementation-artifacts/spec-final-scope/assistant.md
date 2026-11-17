# Assistant design

Fixed decisions for stories 4 and 5. Each story spec adds routes, schemas and tools on top.

## Module layout

- The assistant is its own feature and the composition root of the tools: each feature keeps its
  tools in an `ai_tools/` folder, and only the assistant imports them. ADR 11 lets a regular
  feature import only core features, so story 4 records this in an ADR and changes the
  import-linter contracts.

## Access

- Website only. A signed-in user with a verified email; invite-link guests (`guest_token`) and unverified users are refused.
- Tools are built per request. The user id comes from the JWT and is bound in a closure; no tool argument carries an identity.

## Turn

- `POST` to send a message answers `text/event-stream`. Events: `thinking`, `chunk`, `action`, `done`, `error`.
- A hand-written tool loop: at most 5 model rounds and 15 tool calls per turn; past either, the turn ends with a fixed fallback text.
- Every round streams (`astream` with the tools bound); text chunks go to the client as they arrive, tool-call chunks are aggregated.
- A turn is capped at 240 s of wall time, then ends with `error`.
- Database transactions stay short: one before the first model call (user message, history, limit check), one after each model call that records its usage, and one after the last (assistant message, pending action). No transaction is open during a model call.
- Validation errors in tool arguments reach the model as an error it can fix, not a generic failure.

## History

- Sessions and messages live in Postgres. The model sees the last 20 messages of the session, with the status of each proposed action appended to its message.
- Sessions without activity for 7 days are deleted; story 4 adds this to the cleanup job that story 3 builds for `refresh_tokens` and `verification_codes`.

## Limits

- Global for the whole system; counters in Postgres (the app stack has no Redis).
- A daily budget of 1 USD, counted from the provider's reported token usage times per-model prices in settings; the day is the restaurant's local day.
- At most 10 turns per minute.
- The budget is soft. Both limits are checked before a turn starts, with no reservation; a started turn finishes, so the overshoot is at most the cost of the turns in flight, each bounded by the per-turn caps and a `max_tokens` per model call in settings. Story 4 states the worst-case overshoot in dollars from those caps, the history window, `max_tokens` and the prices in settings.
- The OpenAI dashboard has no daily limit, only a monthly hard spend limit per organization or project, active with "Enforce a hard limit"; its enforcement lags, so recorded spend can slightly exceed it ([spend limits](https://developers.openai.com/api/docs/guides/spend-limits)). It is the monthly backstop, not the daily budget.
- Usage is recorded after every model call, so a turn that dies midway still counts what it spent.
- Exhausted: `429` with an error code and the reset time, before any stream starts.

## Confirmed writes

- A write tool checks access and the domain rules and builds a preview; it writes nothing.
- The proposal is stored as a pending action: `kind`, `payload` with pinned ids, `card`, `expires_at` 24 h after creation, `status` one of `pending`, `applied`, `cancelled`, `expired`, `failed`, plus `result` or `error`.
- One pending card per session: a new proposal cancels the previous pending one.
- The `action` event comes after the last `chunk` and before `done`; the card belongs to that assistant message and reads back with the history.
- The client sends only the action id to apply or cancel.
- Apply re-checks access and the domain rules through the same services as the HTTP routes, then writes. Claiming the row is one atomic `UPDATE ... WHERE status = 'pending'`; a repeated Apply executes nothing.
- After Apply the assistant streams a short comment on the outcome, with no tools bound. Its usage counts toward the budget. When the budget is exhausted, Apply still runs and the comment is a fixed text with no model call.
- Card text is English. The model's reply is in the user's language.

## Key and environments

- Settings with prefix `OPENAI_`: `OPENAI_API_KEY`, `OPENAI_MODEL` and the token prices.
- Local: `backend/.env`, filled by Vlad. Dev: a secret in the GitHub Environment `dev`, passed by `delivery.yml` and `deploy/app/compose.yml` as optional.
- Without a key the assistant routes answer `503`; the rest of the API runs. Tests use a hand-written fake model.

## Frontend rules

- The frontend reaches the API through its own Next.js server; the streaming routes need route handlers that pass the stream through instead of reading the whole body.
- Vercel functions run at most 300 s on Hobby with fluid compute, streamed responses included ([duration limits](https://vercel.com/docs/functions/limitations#max-duration)); the streaming route handlers set `export const maxDuration = 300`.

## Not copied from the reference implementation

- The model name in code, a reply sliced into fake chunks, the full history sent with no trim, a database transaction held open across model calls, token estimates from word counts.

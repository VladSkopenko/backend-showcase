---
title: 'Assistant: global limits'
type: 'feature'
created: '2026-11-18'
status: 'done'
baseline_commit: 'c77544ca838ea693dd439f37b3a832fef2a77412'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/assistant.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/stories/4b-assistant-streamed-turn.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After 4b every turn spends money on the provider with nothing in the system that stops it; the key cannot go to dev until spending has a ceiling.

**Approach:** Record the provider's reported usage of every model call with its cost, refuse a turn before the stream once the day's spend reaches a global budget or the global turns-per-minute cap is hit, state the worst-case overshoot in dollars, and put the key into the dev deployment with Vlad (CAP-6).

## Boundaries & Constraints

**Always:**
- Both limits are global for the system. At most `ASSISTANT_TURNS_PER_MINUTE` user messages in the last 60 s: 429 `ASSISTANT_BUSY`, `retry_after` until the oldest counted one is a minute old. A daily budget `ASSISTANT_DAILY_BUDGET_USD` over the restaurant's local day (`BOOKING_TIMEZONE`), counted as the sum of `assistant_model_calls.cost_micro_usd` since local midnight: 429 `ASSISTANT_BUDGET_EXHAUSTED`, `retry_after` until the next local midnight. Both checked in the turn's first transaction, before the stream, with no reservation; a started turn finishes. `Retry-After` header on both.
- After every model call, in its own short transaction, one `assistant_model_calls` row: `model`, `input_tokens` (cached included), `cached_input_tokens`, `output_tokens`, `cost_micro_usd = round((input - cached) * p_in + cached * p_cached + output * p_out)` with the `OPENAI_*` prices per million. A call cut off before its usage chunk records nothing; it is bounded by `OPENAI_MAX_OUTPUT_TOKENS`. The rows are never deleted.
- Settings: `OpenAISettings` gains `input_price_per_million_usd`, `cached_input_price_per_million_usd`, `output_price_per_million_usd`; `AssistantSettings` gains `daily_budget_usd` and `turns_per_minute`; all in `.env.example`.
- Dev: `OPENAI_API_KEY` from the GitHub Environment `dev` through `delivery.yml` and `deploy/app/compose.yml` as `${OPENAI_API_KEY:-}`, written with Vlad one file at a time after the code, each key explained with a documentation link, checked locally first.
- Tests and CI never call the provider; the fake model's final chunk carries `usage_metadata`.

**Never:** Per-user limits; a reservation or a hard stop of a running turn; token estimates; Redis; changes to the routes or events of 4b; the subagent editing `delivery.yml` or `deploy/app/compose.yml`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Usage recorded | fake model answers in two rounds, each with a usage chunk | two rows with the tokens and the cost from the prices | N/A |
| Cost arithmetic | usage 1000 input of which 200 cached, 50 output, prices 0.40 / 0.10 / 1.60 | `cost_micro_usd` = 800×0.40 + 200×0.10 + 50×1.60 = 420 | N/A |
| Budget reached | rows of today sum to the budget | no stream, no message saved | 429 `ASSISTANT_BUDGET_EXHAUSTED`, `retry_after` = seconds to local midnight, `Retry-After` header |
| Budget boundary | rows of yesterday (local day) above the budget, today none | the turn runs | N/A |
| Cut-off call | fake model raises before its usage chunk | no row for that call; rows of finished calls stay | `error` as in 4b |
| Busy | `turns_per_minute` user messages in the last 60 s | no stream | 429 `ASSISTANT_BUSY` with `retry_after` |
| Busy window | the oldest of those messages is 61 s old | the turn runs | N/A |
| Checks order | no key and the budget exhausted | 503, the budget is not read | 503 `ASSISTANT_UNAVAILABLE` |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/assistant/models/assistant_model_call.py`, `migrations/versions/0023_create_assistant_model_calls.py`, `model_registry.py` -- `id`, `model` String(100), the three token counts, `cost_micro_usd` BigInteger, `created_at` indexed; `down_revision` "0022".
- `backend/src/app/features/assistant/services/usage_ledger.py` -- `UsageLedger(session, prices, timezone, budget, turns_per_minute)`: `check(now=)` raising `AssistantBusyError(retry_after)` or `AssistantBudgetExhaustedError(retry_after)`, `record(usage=, model=)`; `services/exceptions.py` and `endpoints/errors.py` add the two 429s (`DomainError.retry_after` is already rendered as the field and the `Retry-After` header by `app/common/error_responses.py:62-81`).
- `backend/src/app/features/assistant/services/assistant_turn_service.py` -- `start()` calls `check` after the session lookup; the loop sums the chunks and calls `record` with `usage_metadata` (`input_tokens`, `input_token_details.cache_read`, `output_tokens`; langchain-openai sends it as one last empty chunk with `stream_usage`).
- `backend/src/app/config/settings.py` -- prices default 0.40 / 0.10 / 1.60 (OpenAI pricing page for `gpt-4.1-mini`, 2026-11-18), budget 1.0, 10 turns per minute; `backend/.env.example`.
- `backend/tests/test_assistant_limits.py` -- the matrix; `backend/tests/test_settings.py` -- the new keys.
- `.github/workflows/delivery.yml:116-135`, `deploy/app/compose.yml:34-56` -- Vlad's files: the secret into the `env:` block and the `printf` stdin line; `OPENAI_API_KEY: ${OPENAI_API_KEY:-}` under the api service with a comment like the email keys.
- `docs/roadmap.md` -- nothing to tick yet.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_assistant_limits.py`, `backend/tests/test_settings.py` -- one test per matrix row, written first and failing -- contract.
- [x] Model, migration 0023, registry, settings, `.env.example`, `UsageLedger`, the turn service, errors -- behaviour.
- [x] With Vlad, after the code: `delivery.yml`, then `deploy/app/compose.yml` -- infrastructure, outside the subagent's dispatch.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean.
- Given the local API with Vlad's key and `ASSISTANT_DAILY_BUDGET_USD` set just above one turn's cost, when a verified user sends two turns, then the first streams and leaves usage rows whose cost matches the tokens, and the second answers 429 `ASSISTANT_BUDGET_EXHAUSTED` with `retry_after` to local midnight and no stream.
- Given dev after deploy with the secret in the GitHub Environment `dev`, when `POST /api/v1/assistant/sessions` is called without a session, then 401 (the key is read, not 503); when a verified user sends a message through `curl -N`, then the chunks arrive while the answer is produced.

## Implementation Notes

- 2026-11-18: implemented by a subagent; after the review patches 838 tests, ruff, format check, mypy (332 files) and 11 import contracts clean. `delivery.yml` and `compose.yml` written by Claude with Vlad, one at a time: actionlint clean, the `printf` line dry-run with a fake key, `docker compose config` renders the key and an empty value without it. The local live budget check was skipped on Vlad's word (the limits are not the main feature; the OpenAI hard limit is 5 USD); the tests cover the matrix. Dev is checked after the merge with `curl -N`.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Code review: a client that disconnects mid-stream leaves the call's input spend unrecorded, so the budget can be bypassed (blind, edge-case) | medium | usage arrives as the last chunk; cancellation stops the read | rejected by Vlad 2026-11-18: accepted as is, bounded by the per-minute cap and the OpenAI monthly hard limit; Design Notes record it |
| Code review: check-then-insert race lets a burst pass the per-minute cap (blind, edge-case) | medium | READ COMMITTED, no lock; project rule: invariants under a lock | patch: `pg_advisory_xact_lock` in `check()`; concurrency test not possible on the shared test connection |
| Code review: the global busy query has no index (blind) | low | only `(session_id, created_at, id)` exists | patch: partial index on `created_at WHERE role = 'USER'` in 0023 |
| Code review: busy `retry_after` with more than N messages untested (blind) | low | the test had exactly N | patch: test with 3 for N=2 |
| Code review: usage without `cache_read` untested (verification-gap) | medium | langchain-openai omits the key when OpenAI sends none | patch: optional in the fake, test |
| Code review: budget exhaustion is silent (blind) | low | 429 to everyone until midnight, no log | patch: `logger.warning` per refusal |
| Code review: `OPENAI_MODEL` above 100 characters breaks every usage insert (edge-case) | low | String(100) column | patch: `max_length=100` |
| Code review: changing the model alone keeps gpt-4.1-mini prices (blind) | low | prices are separate settings | patch: `.env.example` comment |
| Code review: the `AIMessage` branch of the chunk conversion is untested (blind) | low | the provider and the fake both stream chunks | rejected |
| Code review: the provider's model snapshot name is not stored (blind) | low | the configured name is enough for the budget | rejected |
| Code review: budget and cap are not passed through compose (blind) | false | the spec passes only the key; the defaults are the intended dev values | rejected |
| Code review: a failing usage insert ends the turn with `SERVER_ERROR` (edge-case) | low | fails closed; only a database error triggers it | rejected |
| Code review: `cache_read` above `input_tokens` gives a negative term (edge-case) | false | the provider counts cached tokens inside the input | rejected |
| Spec review: micro-dollar rounding unstated | low | the formula yields fractions | patch: `round()`, a worked row |
| Spec review: Cyrillic token rate assumed | low | measured 2026-11-18 with o200k_base: Ukrainian 2.3, Russian 3.3, English 3.9 characters per token | patch: measured rate noted, bound kept |

## Design Notes

**Worst-case overshoot in dollars** (CodeRabbit's open remark on #44). Symbols: R `max_rounds`, C `max_tool_calls`, H `history_messages`, U the user text cap, O `max_output_tokens`, T `tool_result_max_chars`, S the system prompt, p_in and p_out the prices per million, N `turns_per_minute`, W `turn_timeout_seconds`. Characters are taken as two per token, below the measured o200k rate of 2.3 for Ukrainian, 3.3 for Russian and 3.9 for English.

```text
input per call   <= S + H*max(U/2, O) + C*T/2          = 2000 + 20*1024 + 15*4000  ≈ 82.5k tokens
input per turn   <= R * input per call                 ≈ 412k tokens  → 412k * 0.40/1M = $0.165
output per turn  <= R * O = 5120 tokens                → 5120 * 1.60/1M = $0.008
cost per turn    <= ≈ $0.17
turns in flight  <= N * ceil(W/60) = 10 * 4 = 40
overshoot        <= 40 * $0.17 ≈ $7, on top of the $1 budget, with the defaults
```

A real turn is about three calls of 5k tokens, ≈ $0.01, so the typical overshoot is cents. The bound shrinks with `ASSISTANT_TURNS_PER_MINUTE`, `ASSISTANT_TURN_TIMEOUT_SECONDS`, `ASSISTANT_MAX_ROUNDS` or `ASSISTANT_TOOL_RESULT_MAX_CHARS`; the OpenAI monthly hard limit stays the backstop (assistant.md).

**Unrecorded spend on a cut-off call.** Usage arrives only as the last chunk, so a call cut off by a client disconnect, a timeout or a provider error records nothing although OpenAI billed its input. Accepted by Vlad on 2026-11-18: a verified user who keeps disconnecting can spend past the daily budget, bounded by `ASSISTANT_TURNS_PER_MINUTE` and the OpenAI monthly hard limit. Draining the stream in the background to read the usage was the rejected alternative.

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

---
title: 'Assistant: the streamed turn'
type: 'feature'
created: '2026-11-18'
status: 'done'
baseline_commit: 'a9b1e54b5a600d3416346d56d8c6bc13003c2465'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/assistant.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/stories/4a-assistant-sessions.md'
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After 4a a session holds messages but nobody answers them.

**Approach:** One route that sends a message and streams the answer over Server-Sent Events through a hand-written tool loop on OpenAI through LangChain, with the menu's two read tools as the first `ai_tools` package and the ADR and import contracts that make the assistant their composition root (the second half of CAP-4). Limits are 4c, the other tools and the language check 4d.

## Boundaries & Constraints

**Always:**
- `POST /assistant/sessions/{session_id}/messages` with `{text}` (1 to 2000 characters), same access as 4a, answers `text/event-stream` with `Cache-Control: no-cache` and `X-Accel-Buffering: no`. It sets the title of a session still named "New chat" to the text cut to 60 characters and moves `updated_at`.
- Events in order: `thinking` (`{}`) before every model call, `chunk` (`{"text"}`) as text arrives, `done` (`{"message_id","created_at"}`) once the assistant message is saved; `error` (`{"code","message"}`) ends the stream instead of `done` and saves no assistant message (the user message stays). Codes: `ASSISTANT_TIMEOUT` only for the turn's wall-clock cap, `ASSISTANT_PROVIDER_ERROR` for any exception out of the model call (a per-request provider timeout included), `SERVER_ERROR` for anything else, logged.
- Every check that can refuse the turn runs before the stream starts and answers plain JSON: access, the session, validation.
- The loop: at most `ASSISTANT_MAX_ROUNDS` model calls per turn and `ASSISTANT_MAX_TOOL_CALLS` tool calls per turn, counted across rounds; a round whose calls would push the count past the cap runs none of them. Past either cap the turn ends with the fixed English fallback text sent as a chunk and saved. Every call streams with `astream` on the model with the tools bound; text chunks go to the client at once, tool-call chunks are summed into one message; a malformed call (`invalid_tool_calls`) and an argument validation error reach the model as error tool messages it can fix; a `DomainError` in a tool becomes `{"error": code, "message"}`; any other tool exception is logged and becomes `{"error": "TOOL_FAILED"}`. The whole turn is under `ASSISTANT_TURN_TIMEOUT_SECONDS` of wall time.
- Transactions are short: one before the first model call (checks, the user message, the history), one per tool call, one at the end (the assistant message). None is open during a model call.
- History: the model sees the last `ASSISTANT_HISTORY_MESSAGES` messages of the session, the new one included, as user and assistant text only; tool messages are not stored.
- The system prompt: the restaurant's assistant on its website; answer in the language of the user's message; plain text; use tools for facts and never invent them; only the restaurant's matters; today's date and time in the restaurant's timezone and the user's first name. Fixed texts (fallback, errors) are English.
- The user's identity reaches tools only from the JWT, bound in the tool context; no tool argument names a user. Tools call the same services as the HTTP routes and copy no rule; shaping a service's result is not a rule. Each tool result is JSON, cut at `ASSISTANT_TOOL_RESULT_MAX_CHARS` with the trailing marker ` …[truncated]`.
- Two tools: `list_menu(category?)` (`DishSort.POPULAR`, `limit=50`, `offset=0`, with `total`; `id`, `name`, `category`, `price`, `is_available`, `weight_grams`, `calories`, `prep_minutes` per dish) and `get_dish(dish_id)` (the full dish with description and nutrition). Prices are decimal strings in USD.
- `AssistantSettings` gains `history_messages`, `max_rounds`, `max_tool_calls`, `turn_timeout_seconds`, `tool_result_max_chars`, in `.env.example`.
- Tests and CI never call the provider: a hand-written fake chat model in `tests/support/`.

**Never:** Limits or usage rows (4c); other tools (4d); write tools, cards or the `action` event (5); token estimates; a tool router; translations; `delivery.yml` and `deploy/app/compose.yml` (4c, with Vlad).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Plain answer | fake model streams text; a 70-character first message | `text/event-stream` with the two headers; `thinking`, `chunk`…, `done`; both messages saved and read back; the title is the 60-character cut; the fake received the system prompt with the user's first name | N/A |
| Tool round | fake model calls `list_menu` then answers | `thinking`, `thinking`, `chunk`…, `done`; the fake received a tool message with the dishes JSON | N/A |
| Dish detail | fake model calls `get_dish` for a seeded dish | the tool message carries description, calories, protein, fats, carbs, vitamins | N/A |
| Bad arguments | fake model calls `list_menu` with `category` "SOUP" | an error tool message naming the field; no `error` event | N/A |
| Malformed call | fake model emits a tool-call chunk with unparseable arguments | an error tool message for that call id; the turn goes on | N/A |
| Domain error in a tool | `get_dish` with an unknown id | `{"error":"DISH_NOT_FOUND",…}`; the turn goes on | N/A |
| Tool crashes | a tool raises something that is not a `DomainError` | `{"error":"TOOL_FAILED"}`; the exception is logged | logged |
| Long result | `tool_result_max_chars` 200 and `list_menu` | the tool message is 200 characters plus the marker | N/A |
| History window | session with 25 messages, `history_messages` 20 | the fake receives the system prompt and the last 20 messages, the new one last | N/A |
| Round cap | fake model calls a tool in every round | after `max_rounds` calls the fallback text is streamed and saved; `done` | N/A |
| Tool-call cap | `max_tool_calls` 15, fake asks for 10 calls in round one and 6 in round two | round one runs 10; round two runs none; fallback text, `done` | N/A |
| Provider fails | fake model raises mid-stream | `error` `ASSISTANT_PROVIDER_ERROR`; the user message stays; no assistant message | logged |
| Turn timeout | fake model stalls past `turn_timeout_seconds` | `error` `ASSISTANT_TIMEOUT` | logged |
| Text limits | empty text, 2001 characters | nothing | 422 `VALIDATION_ERROR` |
| Foreign session | another user's session id | nothing | 404 `ASSISTANT_SESSION_NOT_FOUND` |

</frozen-after-approval>

## Code Map

- `backend/pyproject.toml` -- add `langchain-openai>=1.8.1` (brings `langchain-core` 1.8, `openai` 3.55, `tiktoken`; resolves on Python 3.14 next to `httpx2`, checked 2026-11-18; both ship `py.typed`). On 3.14 `import langchain_openai` raises `DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated` from `langchain_core`, and `filterwarnings = ["error"]` would fail the suite: add one entry `"ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning"` with a comment naming the package. Import contracts: `ai_tools` joins the layers as `"(endpoints) | (ai_tools)"` (independent, optional; parses in import-linter 2.15); add `app.features.*.ai_tools` and `app.features.core.*.ai_tools` to the sources of "Endpoints never import repositories or models", "Only endpoints import schemas" and "Code below endpoints knows nothing about HTTP"; "Regular features are independent" gets `ignore_imports` for `app.features.assistant.** -> app.features.*.ai_tools` and `.ai_tools.**`; a new `protected` contract "Only the assistant imports ai_tools" with `protected_modules` `app.features.*.ai_tools`, `app.features.core.*.ai_tools` and `allowed_importers` `app.features.assistant.**`.
- `docs/adr/0020-assistant-composes-ai-tools.md` -- the assistant feature is the composition root: `ai_tools/` beside `endpoints/` is a second adapter over `services` (imports services and dto only), every feature may own one, only the assistant imports them; why not `application_services` (cross-feature work, not model-facing adapters). Amend ADR 11's status line; README ADR rows (`README.md:104` area, `README.uk.md` likewise).
- `backend/src/app/features/assistant/services/` -- `AssistantTurnService` taking the sessionmaker, the model, the settings values and the user: `start()` runs the first transaction and raises, `stream()` is the async generator and owns the stream error codes as class attributes; `SystemPromptBuilder` from `BookingSettings.timezone` and `clock`; `ToolkitBuilder` importing the `ai_tools` packages. `endpoints/dependencies.py` -- `get_chat_model` returning `ChatOpenAI(model=, api_key=, max_tokens=, timeout=, max_retries=1, stream_usage=True, use_responses_api=False)` (names checked in langchain-openai 1.8.1) so tests override it with the fake; `assistant.py` -- the route returning `StreamingResponse(media_type="text/event-stream")` after `start()`.
- `backend/src/app/common/ai_tools.py` -- what every `ai_tools` package shares, importing nothing from features: `AiToolContext(user_id, sessionmaker, public_base_url)` (4d adds fields), the error payload shape, the result cut.
- `backend/src/app/features/core/menu/ai_tools/` -- `MenuTools(context).build() -> list[BaseTool]`; each tool is `StructuredTool.from_function(coroutine=…, args_schema=…, handle_validation_error=…)` with a Pydantic args model whose every field has a description; a tool opens its own session per call through the sessionmaker and builds `DishCatalogService` as `menu/endpoints/dependencies.py` does; `dish_catalog_service.py:18-34` unchanged.
- `backend/src/app/config/settings.py` -- defaults 20 messages, 5 rounds, 15 calls, 240 s, 8000 chars; `gt=0`; `backend/.env.example`.
- `backend/tests/support/fake_chat_model.py` -- a `BaseChatModel` subclass with a scripted `_astream` (text chunks, `tool_call_chunks`, a final empty chunk), `bind_tools` recording the tools and returning itself, the received messages kept for assertions; scripts that raise and that wait. `backend/tests/support/sse.py` -- parse an event-stream body into `(event, data)` pairs.
- `backend/tests/test_assistant_turn.py` -- the matrix through the API with `app.dependency_overrides[get_chat_model]`; `backend/tests/test_settings.py` -- the new keys; `backend/tests/test_openapi.py:57` -- the fourth route in flow "Assistant".
- Caddy: `reverse_proxy` flushes `text/event-stream` at once by default; the dev check in 4c confirms it with `curl -N`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/support/fake_chat_model.py`, `backend/tests/support/sse.py` -- the fake model and the SSE parser -- test infrastructure.
- [x] `backend/tests/test_assistant_turn.py`, `backend/tests/test_settings.py`, `backend/tests/test_openapi.py` -- one test per matrix row, written first and failing -- contract.
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- the dependency, the warning filter, the import contracts -- behaviour.
- [x] Settings, `.env.example`, `app/common/ai_tools.py`, `core/menu/ai_tools/`, the turn service, the prompt and toolkit builders, the route -- behaviour.
- [x] `docs/adr/0020-assistant-composes-ai-tools.md`, ADR 11 status line, README ADR rows -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` (11 contracts) are clean.
- Given the local API with Vlad's key in `backend/.env`, when a verified user asks in English what desserts there are and what is in one of them, then the chunks arrive through `curl -N` while the answer is produced, the answer names dishes the menu routes return, and the session reads back with both messages and the title.

## Implementation Notes

- 2026-11-18: implemented by a subagent from this spec; tests first, confirmed failing (the turn tests at collection on the missing `get_chat_model`, the settings and OpenAPI tests on the missing keys and route).
- The deprecation warning the Code Map predicts comes from `langsmith` (imported by `langchain-core`, which also registers a pytest plugin), not from `langchain_core` itself; the filter text is as specified and the comment names `langsmith`.
- `get_chat_model` passes `max_completion_tokens=`, the alias of `ChatOpenAI.max_tokens`: mypy accepts only the alias for the synthesized constructor, and at runtime both names set the same field (checked: `.max_tokens == 1024`).
- `EventStreamResponse` (`endpoints/event_stream.py`, a `StreamingResponse` subclass) encodes `AssistantEvent` dto objects with `pydantic_core.to_json`, so `created_at` has the API's usual `Z` form. Its media type is set per instance, not on the class: FastAPI documents every response of a route with the class-level media type, and `test_error_responses.py` pins the 4xx responses to `application/json`. The route sets `status_code=200` explicitly because FastAPI reads the default from the response class's `__init__`, which has no such parameter; `test_openapi.py` pins the 200 as `text/event-stream` and the refusals as JSON.
- Malformed calls: langchain's partial-JSON parser turns `{oops` into `{}` (a valid call with no arguments); only a non-object such as `not json` lands in `invalid_tool_calls`. The error tool message carries the code `MALFORMED_CALL`; argument validation errors carry `INVALID_ARGUMENTS` with `field: message` pairs (`app/common/ai_tools.py`).
- A tool name the toolkit does not know raises `KeyError` inside the tool `try`, so it answers the model with `TOOL_FAILED` and the turn goes on; OpenAI only calls bound tools, so no row covers it (the note corrected by the parent after review).
- The fake model keeps a `Received`-style list of the messages of every call and has an `Act` step that runs a callback mid-stream; the tests use it to move the fake clock so the two messages of a turn get distinct timestamps (with equal `created_at` the read-back order falls to random ids).
- Subagent's run from `backend/`: `uv run pytest` 811 passed in 278 s; `ruff check` and `ruff format --check` clean (350 files); mypy clean on 327 files; `lint-imports` 11 kept. Not done: the live check with Vlad's key (acceptance criterion 2).

- 2026-11-18, parent session after the review patches: 817 tests, ruff, format check, mypy (327 files) and 11 import contracts clean. Live, local `app` at 0022, API on port 8010 with Vlad's key and email off, model `gpt-4.1-mini`: a verified `live4b-…@example.com` (first name Olena) asked in English about desserts and the cheapest one, then what is in it. `curl -N` showed `thinking`, a second `thinking` after the `list_menu` round, then `chunk` events arriving over about two seconds and `done`; headers `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`. The second turn ran `list_menu` and `get_dish` and answered Lemon Basil Sorbet, 190 kcal, three scoops with basil and lemon zest, as `GET /menu/dishes/{id}` returns; it ties at $8 with Pelamushi Grape Pudding. The session read back with four messages and the first question as its title. One of the first two runs answered the English question in Ukrainian; after the prompt fix (language rule first, never from the name) five fresh sessions with the same question all answered in English, naming both $8 desserts. The API was stopped cleanly.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Live check: an English question from a user named Olena answered in Ukrainian on one of two runs | medium | the prompt named the guest before the language rule | patch: the language rule first, never guessed from the name; 5 of 5 English after |
| Code review: text streamed in a tool round is not in the saved message (edge-case, blind, verification-gap, parent) | medium | `_finish(str(reply.text))` saves the last round only; the client showed every chunk | patch: one buffer of every chunk sent |
| Code review: an empty final reply saves an empty message (edge-case) | low | no guard on `reply.text` | patch: fallback text |
| Code review: the last round's tool calls run with no model call left (edge-case, blind) | low | wasted DB work per capped turn | patch: skip, as the tool-call cap does |
| Code review: invalid tool calls do not count toward the tool-call cap (edge-case) | low | `max_rounds` bounds them; they cost no tool work | rejected |
| Code review: two overlapping POSTs to one session interleave (edge-case) | low | one user double-sending; a lock or a 409 is new surface | rejected |
| Code review: whitespace-only text accepted (edge-case, blind) | low | `min_length=1` on the raw value | patch: strip before validation |
| Code review: equal `created_at` orders by random id (edge-case) | false | only the fake clock produces equal stamps; the two messages of a turn are written at `start()` and `_finish()` | rejected |
| Code review: `list_menu` does not say 50 is the cap (edge-case, blind) | low | 30 dishes seeded | patch: description |
| Code review: the warning filter is not scoped to langsmith (edge-case, verification-gap) | false | checked: the warning is attributed to `asyncio.coroutines`, a module-scoped filter does not catch it | rejected |
| Code review: unknown tool name ends in `TOOL_FAILED`, the notes said `SERVER_ERROR` (verification-gap) | low | `self._tools[name]` sits inside the `try` | patch: Implementation Notes corrected by the parent |
| Code review: a `ChatOpenAI` client per request, never closed (blind) | low | an httpx client per turn at ten turns a minute | defer: build once per process as `oauth_clients` |
| Code review: `langchain-core` imported directly, not declared (blind) | low | six modules import it | patch: `uv add langchain-core` |
| Code review: the four refusal tests skip the messages route (blind, verification-gap) | medium | `VerifiedUserDep` can be dropped from the turn dependency unnoticed | patch: fourth request in each list |
| Code review: `_transaction` duplicates `get_session` (blind) | low | six lines; a shared helper touches `common` | rejected |
| Code review: "no lists of symbols" in the prompt (blind) | low | wording | patch |
| Code review: route description omits that the title is set even when the turn fails (blind) | low | `start()` commits before the model call | patch: one sentence |
| Code review: ADR 20 says "never" where the contract allows indirect imports (blind) | low | `allow_indirect_imports` | patch: "directly" |
| Code review: the fake's `assert` surfaces as a provider error (blind) | low | test ergonomics | patch: distinct exception |
| Code review: the title guard on a second message is unpinned (verification-gap) | medium | every test sends once | patch: test |
| Code review: `updated_at` on the error path is unobserved (verification-gap) | low | only `touch()` is asserted | patch: test |
| Code review: `SERVER_ERROR` stream event untested (verification-gap) | medium | nothing raises past the narrower handlers | patch: test |
| Code review: `get_chat_model` never executed (verification-gap) | medium | every test overrides it | patch: constructor test |
| Spec review: which codes are `DomainError`s, where the stream codes live, when `SERVER_ERROR` | medium | `main.py:128-145` handlers cannot run inside a stream | patch |
| Spec review: a per-request provider timeout is both a timeout and a provider error | medium | `request_timeout_seconds` and `turn_timeout_seconds` | patch: mapping stated |
| Spec review: tool-call cap ambiguous (partial round, cumulative) | medium | matrix row tested one round | patch: cumulative, a round over the cap runs nothing |
| Spec review: `list_menu` does not say `sort`, `limit`, `offset` | medium | `dish_catalog_service.py:18-20` | patch |
| Spec review: no matrix rows for the cut marker, malformed calls, `TOOL_FAILED`, the headers, the title | medium | frozen promises without tests | patch: rows added |
| Spec review: `filterwarnings = ["error"]` fails on a third-party deprecation | high | `import langchain_openai` under `-W error` on 3.14 raises from `langchain_core` | patch: one targeted filter |
| Spec review: import contracts verified in import-linter 2.15 | false | parsed and kept on the current tree | none |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean, 11 contracts kept

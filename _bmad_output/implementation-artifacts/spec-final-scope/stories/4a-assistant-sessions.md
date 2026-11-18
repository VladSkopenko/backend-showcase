---
title: 'Assistant: sessions'
type: 'feature'
created: '2026-11-18'
status: 'done'
baseline_commit: 'a9b1e54b5a600d3416346d56d8c6bc13003c2465'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/assistant.md'
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The website has nowhere to keep a guest's chat with the assistant, and the frontend has no API to build one on.

**Approach:** A new `assistant` feature with chat sessions and their messages in Postgres, three routes to create, list and read them, access for verified users only, the 7-day cleanup in the existing `CleanupJob`, and the provider settings (the first half of CAP-4). The streamed turn is story 4b.

## Boundaries & Constraints

**Always:**
- Only new routes under `/api/v1/assistant`; nothing existing changes shape. Access: a signed-in user (`CurrentUserDep`, else 401 `NOT_AUTHENTICATED`) with a verified email, else 403 `EMAIL_NOT_VERIFIED` (the existing error reused; no API flow signs an unverified user in, so it is a guard); the `guest_token` cookie alone is 401. Without `OPENAI_API_KEY` every assistant route answers 503 `ASSISTANT_UNAVAILABLE`; the rest of the API runs. The key check reads `Settings` through `Depends(get_settings)`, so tests switch it per module with `app.dependency_overrides[get_settings]` on a fresh `create_app()`.
- Routes: `POST /assistant/sessions` (201), `GET /assistant/sessions` (the caller's sessions, latest activity first, not paginated), `GET /assistant/sessions/{session_id}` (with its messages oldest first; another user's or unknown id is 404 `ASSISTANT_SESSION_NOT_FOUND`). A session is `{id, title, created_at, updated_at}` in the list and the detail alike; the detail adds `messages: [{id, role, text, created_at}]`, `role` one of `USER`, `ASSISTANT`. The title is "New chat" until story 4b sets it from the first message; `updated_at` moves on every message.
- Settings: `OpenAISettings` (`OPENAI_`: `api_key`, `model`, `max_output_tokens`, `request_timeout_seconds`) and `AssistantSettings` (`ASSISTANT_`: `session_ttl_days`), in `.env.example`; 4b and 4c add their keys.
- `CleanupJob` also deletes sessions whose `updated_at` is `ASSISTANT_SESSION_TTL_DAYS` old or older (messages cascade). Its INFO line becomes "Deleted %d expired refresh tokens, %d old verification codes and %d inactive assistant sessions", emitted when any count is non-zero.

**Never:** Sending a message, the model, LangChain or any tool (4b); deleting or renaming a session by hand; pagination; translations; Telegram; `delivery.yml` and `deploy/app/compose.yml` (4c, with Vlad).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create and list | verified user creates two sessions; the first gets a message row with a later `updated_at` through the test session | 201 with the four fields and `title` "New chat"; the list has the first session first | N/A |
| Read back | a session with a user and an assistant message inserted by the test | both messages oldest first, each with `id`, `role`, `text`, `created_at` | N/A |
| Unverified user | a verified user logs in, then the test nulls `email_verified_at` on the connection | nothing | 403 `EMAIL_NOT_VERIFIED` |
| Guest or nobody | only `guest_token`, or no cookie | nothing | 401 `NOT_AUTHENTICATED` |
| No key | settings with an empty `OPENAI_API_KEY`, any assistant route | nothing | 503 `ASSISTANT_UNAVAILABLE` |
| Foreign session | another user's session id, or unknown | nothing | 404 `ASSISTANT_SESSION_NOT_FOUND` |
| Cleanup | sessions updated 7 days ago and 6 days ago | the old one and its messages gone, the other kept; the INFO line carries three counts | N/A |
| Lifespan | app start and shutdown | the "cleanup" and "request expiry" tasks both start and stop (names only, as today) | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/config/settings.py` -- the two classes; `api_key: SecretStr = SecretStr("")` with `is_configured`; defaults `model="gpt-4.1-mini"`, `max_output_tokens=1024`, `request_timeout_seconds=60`, `session_ttl_days=7`; `gt=0`. `backend/.env.example`; `tests/conftest.py:53-64` prefix list gets `OPENAI_` and `ASSISTANT_`, so every assistant test module builds its app with `Settings(openai=OpenAISettings(api_key=SecretStr("test")))` overriding `get_settings`, as `tests/test_cleanup.py` and `tests/test_google_oauth.py:93-102` do.
- `backend/src/app/features/assistant/` -- regular feature: `models/` (`AssistantSession`: `id`, `user_id` FK users CASCADE, `title` String(100), `created_at`, `updated_at`, index `(user_id, updated_at)`; `AssistantMessage`: `id`, `session_id` FK CASCADE, `role` enum `assistant_message_role`, `text` Text, `created_at`, index `(session_id, created_at, id)`), `enums/`, `repositories/`, `dto/`, `schemas/`, `services/` (`AssistantSessionService` for create, list, get; `AssistantCleanupService.delete_inactive(now=)`; `exceptions.py` with `AssistantUnavailableError`, `AssistantSessionNotFoundError`), `endpoints/` (`dependencies.py`: `VerifiedUserDep` on top of `CurrentUserDep`, a router-level dependency raising `AssistantUnavailableError` when the key is empty; `errors.py` with 503 and 404; `openapi_tags.py` tag "Assistant"; `assistant.py` the three routes).
- `backend/src/app/model_registry.py`, `backend/migrations/versions/0022_create_assistant_tables.py` -- two tables and the enum; `down_revision` "0021".
- `backend/src/app/infrastructure/background_tasks/cleanup_job.py:5-27`, `backend/src/app/main.py:61-77,89-103` -- `CleanupJob(sessionmaker, assistant_session_ttl_days=)`; the router with prefix `/api/v1`; `ERROR_STATUSES`; the tag between `PreorderOpenApiTags.METADATA` and `BookingOpenApiTags.STAFF_METADATA`, matching the flow order in `tests/test_openapi.py`. `CleanupJob` importing `app.features.assistant.services` is intended (story 3 precedent with core auth).
- `backend/src/app/features/core/auth/services/exceptions.py:54` -- `EmailNotVerifiedError` reused.
- `backend/tests/test_assistant.py` -- the matrix through the API; `backend/tests/test_cleanup.py` -- the cleanup rows, the INFO assertion updated; `backend/tests/test_settings.py` -- the two blocks; `backend/tests/test_openapi.py:57` -- flow "Assistant" with the three routes after "Pre-order".
- `README.md:32`, `README.uk.md` -- unchanged until 4d.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_assistant.py`, `backend/tests/test_cleanup.py`, `backend/tests/test_settings.py`, `backend/tests/test_openapi.py` -- one test per matrix row, written first and failing -- contract.
- [x] Settings, `.env.example`, conftest prefixes; models, enum, migration 0022, registry -- behaviour.
- [x] The `assistant` feature, `main.py`, `CleanupJob` -- behaviour.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean.
- Given the local API with Vlad's key in `backend/.env`, when a verified user creates a session, then it lists and reads back empty; without the key the same routes answer 503 and `/health` stays ok.

## Implementation Notes

- 2026-11-18: implemented by a subagent from this spec; tests first, confirmed failing at collection.
- Feature `features/assistant`: `AssistantSessionService` (`create` with title "New chat", `list`, `get` returning `AssistantSessionView` with the messages), `AssistantCleanupService(session, session_ttl_days=).delete_inactive(now=)` as a bulk `DELETE ... WHERE updated_at <= now - ttl`; repositories order the list by `updated_at desc, id desc` and the messages by `created_at, id`.
- Endpoints: the key check `require_assistant_configured` is a router-level dependency on `Depends(get_settings)`; `VerifiedUserDep` raises `EmailNotVerifiedError` on top of `CurrentUserDep`; `DOCUMENTED_ERROR_STATUSES` adds the auth statuses for the docs. The two body-less routes use `takes_input=True`, as FastAPI documents a 422 on every route reading the access cookie (`test_error_responses` pins it).
- Migration 0022: both tables, the enum `assistant_message_role` and the two indexes; downgrade and upgrade round-tripped on `app_test`.
- `CleanupJob(sessionmaker, *, assistant_session_ttl_days)` deletes the sessions in the same transaction as the auth rows; the INFO line carries three counts.
- Subagent's run from `backend/`: `uv run pytest` 785 passed; ruff check and format check clean; mypy clean on 314 files; `lint-imports` 10 kept.
- 2026-11-18, parent session after the review patches: 787 tests, ruff, format check, mypy (314 files) and 10 import contracts clean. Live, local `app` migrated 0019 -> 0022 by Claude on Vlad's word (0020 adds the dev guest bots locally too), API on port 8010 with Vlad's key from `backend/.env` and email off: anonymous 401; registered, verified and logged in `live4a-…@example.com` through the API; two sessions created (201, four fields, "New chat"), the list has the newer first, the read answers `messages: []`, `not-a-uuid` answers 422 with `field: session_id`, a second user `live4a-other-…@example.com` gets 404 `ASSISTANT_SESSION_NOT_FOUND`, a `guest_token` cookie alone gets 401. Restarted with `OPENAI_API_KEY=` empty: the three routes answer 503 `ASSISTANT_UNAVAILABLE`, `/health` ok and the menu 200. Both API runs stopped cleanly.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Code review: 403 asserted only on `POST /sessions`; the two GET routes can lose `VerifiedUserDep` unnoticed (verification-gap, blind) | medium | `test_assistant.py` posts once; the 401 and 503 tests loop over three routes | patch: three requests |
| Code review: the lifespan passes the TTL to `CleanupJob` unobserved (verification-gap) | medium | the lifespan test asserts task names only; same shape as the interval wiring deferred in story 3 | defer: deferred-work entry |
| Code review: whitespace-only key counts as configured (edge-case) | low | `is_configured` tests `bool(value)`; a key with a stray space fails at the provider in 4b with a clear error | rejected: unlikely, a guard for undemonstrated state |
| Code review: empty `OPENAI_MODEL` loads and fails at the first model call (edge-case, blind) | low | `model: str = "gpt-4.1-mini"` has no bound; `.env.example` style invites `OPENAI_MODEL=`; precedent `MEDIA_PUBLIC_BASE_URL` has `min_length=1` | patch: `min_length=1` and a test |
| Code review: a TTL above timedelta's limit raises every run (edge-case) | low | `timedelta(days=10**9)` overflows; nobody sets that | rejected |
| Code review: a session deleted between the two reads answers 200 with no messages (edge-case) | low | two statements in one request; the next request answers 404 | rejected: no harm, the fix adds a join or a re-check |
| Code review: 503 wins over 401 for an anonymous caller without a key, unpinned (blind) | low | router-level dependency runs first; the spec says every assistant route answers 503 without a key | patch: pinned by a request without a cookie |
| Code review: no 422 test for a non-UUID `session_id` (blind) | low | sibling modules pin it (`test_preorder.py:361`, `test_invites.py:301`) | patch: test |
| Code review: `CleanupJob` reads the clock twice in one run (blind) | low | `AuthCleanupService` reads `clock.now()` itself; the spec fixes `delete_inactive(now=)` | rejected: milliseconds apart, no consequence |
| Code review: `POST /sessions` description says "its id" (blind) | low | the response has four fields | patch |
| Code review: `.env.example` tails missing on two OpenAI keys (blind) | low | the file's convention | patch |
| Code review: cleanup test name says "both counts" (blind) | low | the assertion has three | patch: rename |
| Spec review: `EmailNotVerifiedError` cited at line 62, lives at 54; its text is a sign-in message | low | `exceptions.py:54-58`; login refuses unverified users | patch: cite fixed, reuse stated |
| Spec review: the unverified-user row has no reachable setup | medium | `login_service.py:47-48` | patch: setup in the row |
| Spec review: with the conftest prefixes cleared every test would hit 503; the key check must read `Depends(get_settings)` | high | `tests/conftest.py:30-64`, `test_google_oauth.py:93-102` | patch |
| Spec review: lifespan row claims the TTL is observable | low | `test_cleanup.py:431-453` asserts names only | patch: reworded |
| Spec review: session fields beyond `id`, `title` unstated | medium | the frontend document needs them | patch |
| Spec review: `CleanupJob` INFO wording change and its test unstated | low | `cleanup_job.py:23-27` | patch |
| Spec review: `test_openapi.py:50` is the Pre-order block; the tag order in `create_app` must match | low | `test_openapi.py:50-58`, `main.py:93-103` | patch |
| Vlad, 2026-11-18: one 7.5k-token spec is too big | high | five stories 4a to 4e | patch: split by capability, then sessions from the turn |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

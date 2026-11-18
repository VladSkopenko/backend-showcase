---
title: 'Backend cleanup: no in-app notifications, review fixes, nothing unused'
type: 'refactor'
created: '2026-11-18'
status: 'done'
baseline_commit: 'f1ad23535757ca267a985e7d51dc7c4c14d09853'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/docs/adr/0013-table-booking-slots-and-double-booking.md'
  - '{project-root}/docs/adr/0018-in-app-notifications.md'
  - '{project-root}/docs/adr/0020-assistant-composes-ai-tools.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After the final scope the backend carries in-app notifications nobody will build a screen for, three functional bugs found in the full review, a model client rebuilt on every turn, and code nothing uses.

**Approach:** Remove in-app notifications completely (decision emails stay), fix the three bugs, build the chat model once per process, and delete everything unused or duplicated. Vlad decided all of it on 2026-11-18.

## Boundaries & Constraints

**Always:**
- **Notifications go.** The routes `GET /notifications` and `POST /notifications/{id}/read`, the `Notification` model, its repository, schemas, DTOs (`NotificationPage`, `NotificationView`), `NotificationService`, `NotificationNotFoundError`, `BookingDecisionNotifier` and every call of it (`BookingRequestService`, `RequestExpiryService`, `RequestExpiryJob`, the bookings dependencies), the tag, the error statuses, the router and the registry entry. A new migration 0025 drops the table `notifications` and the enum `notification_kind`; its downgrade recreates both as 0019 did. 0019 is not edited. `DecisionNotice`, `NoticeRecipient`, the `NotificationKind` Python enum, `DecisionEmailService`, its renderer, the templates and `NotificationSettings.skip_email_domains` stay. Decision emails are sent exactly as today.
- **The recipient lock goes with them.** The account-holder row locks in approve, reject and the sweep exist only for the notification inserts; they go with `BookingParticipantRepository.lock_account_holders`, the services' now unused `_participants` and the `decided_at` parameter of `_outcome`. ADR 13 is amended (lines 13-14, 90-92, 136-144): decisions no longer lock account holders; the `decided_by_id` write still key-share locks the staff user row after the table and booking, a known exception.
- **ADR 21** "Decisions reach guests by email only" supersedes ADR 18: why (no frontend list, the email links to the reservations page, the booking card shows the status, realtime delivery is not worth it); ADR 18's status says superseded; README rows and the roadmap follow.
- **Search hides starts a request cannot take.** A new predicate `BookingSchedule.is_requestable_start(starts_at=, now=)` holds the rule; `check_requestable_start` uses it, and `TableSearchService` marks a start unavailable with it when `initial_status(party_size)` is `PENDING`. `is_free` and the edit-slots route stay unchanged (request bookings are never editable). The search route's description gains one sentence about the request lead; the assistant's `find_tables` gets the rule through the same service.
- **Edit locks in the ADR 13 order.** `BookingService.edit` takes an optional `expected` (start, party size and duration, all three or none); right after its locked re-read of the booking and before the participant count and overlap checks, it raises `BookingChangedError` when the booking's start, party size or `ends_at − starts_at` differ. The assistant's edit applier passes the pinned "before" values and no longer calls `lock_owned`. Without `expected`, `PUT /bookings/{id}` behaves exactly as today.
- **Neutral apply text.** The fixed comment after an applied card is "Done." for every kind; the failed text stays "That did not work: <message>".
- **One chat model per process.** A builder `build_chat_model(openai: OpenAISettings) -> ChatOpenAI | None` (None without a key) makes the model with the same arguments as today and no custom http client (langchain-openai already shares one cached httpx pool per process, so nothing is closed and `openai` stays an indirect dependency). `create_app` stores its result in `app.state.chat_model`; `get_chat_model(request)` returns it or raises `AssistantUnavailableError`; the 503 gate stays on the settings. The turn and the apply share the instance; tests keep overriding `get_chat_model`.
- **Unused and duplicated code goes:** `AppSettings.backend_url` and `APP_BACKEND_URL`; `GET /` with `RootResponse`, and `AppSettings.name` and `APP_NAME` (read only by the root route and the OpenAPI title, which becomes the literal "backend-showcase"); the duplicate `httpx2` in the dev group (`uv.lock` regenerated); the menu seed's database writes, so the seed reads the image keys from the database and only uploads pictures, as the location seed does (`DishSeedService.save`, `load` of `dishes.json`, `DishSeedEntry`, `DEFAULT_PREP_MINUTES`, `_prep_minutes`, `DishRepository.upsert_by_slug` and `CONTENT_COLUMNS` go; a missing picture still fails before any upload); one helper `sha256_hex` in `app/common/hashing.py` for the three identical copies (stored hashes stay valid); one method `ProposalSink.propose(kind=, payload=, card=) -> str` returning the identical `{"status": "awaiting_confirmation", "card": …}` result for the four copies.
- Only removals and the fixes above; no other route or response shape changes. The frontend copy that mentions notifications is a frontend task, not changed here.

- The `notifications` package stays as the home of the decision emails (`NOTIFICATIONS_` settings and the template loader depend on its name): `endpoints/__init__.py` stays, emptied; `endpoints/dependencies.py` keeps only the renderer and email-service providers and aliases; the import contract stays with its comment pointing at ADR 21.

**Never:** Removing decision emails; editing migration 0019; touching `deploy/`, CI, n8n or Grafana; changing routes other than removing the two notification routes and `GET /`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Decision email | staff approves and rejects a request; the auto-reject sweep rejects one | the owner gets the decision email as before; no notification row, no table | N/A |
| Notification routes gone | `GET /api/v1/notifications` | nothing | 404 |
| Migration | upgrade to 0025, downgrade to 0024, upgrade again | the table and enum are absent, then present, then absent | N/A |
| Request lead in search | now 18:00, party of 6, today | starts up to 20:00 on request tables are unavailable; later ones free; a party of 4 still sees 18:30 | N/A |
| Edit changed elsewhere | the assistant's edit card applied after a website edit | `FAILED` `BOOKING_CHANGED`, the website's values kept, locks taken user, table, booking | N/A |
| Route edit unchanged | `PUT /bookings/{id}` without expected values | behaves exactly as today | N/A |
| Apply text with the budget spent | apply a cancel card when the budget is exhausted | comment "Done." | N/A |
| One model | `create_app` with a key | `app.state.chat_model` is one `ChatOpenAI` built by `build_chat_model` with the settings' model, max tokens and timeout | N/A |
| No key | `build_chat_model` without a key | `None`; `get_chat_model` raises `ASSISTANT_UNAVAILABLE` | 503 |
| Root route gone | `GET /` | nothing | 404 |
| Menu seed | run against a database with the dishes | uploads the pictures named by the dishes' image keys, writes nothing to the database | N/A |
| Menu seed, missing picture | one picture file absent | fails before any upload | error |
| Search with time | party of 6 inside the lead, `time` set | the table is not listed; `total` excludes it | N/A |
| Tomorrow | party of 6 tomorrow | unaffected | N/A |
| Edit slots | `GET /bookings/{id}/slots` | unchanged | N/A |
| Assistant search | `find_tables` for 6 today inside the lead | the starts are absent from `free_start_ranges` | N/A |
| Edit after a website cancel | the assistant's edit card applied after the booking was cancelled | `FAILED` with the code `edit` gives for a cancelled booking | N/A |
| Old hashes | a refresh token, guest token and verification code stored before the change | still accepted | N/A |

</frozen-after-approval>

## Code Map

- Inventory (2026-11-18 review): `backend/src/app/features/core/notifications/` — delete `dto/notification_page.py`, `dto/notification_view.py`, `endpoints/{notifications,errors,openapi_tags,__init__}.py`, `models/`, `repositories/`, `schemas/`, `services/{booking_decision_notifier,notification_service,exceptions}.py`; trim `dto/__init__.py:3-6` and `endpoints/dependencies.py` (keep the renderer and email-service providers). Elsewhere: `main.py:36-40,56,109,135`; `model_registry.py:17,35`; `core/bookings/services/booking_request_service.py:35-36,48,56,88-90,165`; `request_expiry_service.py:14-15,24,30,39-47`; `core/bookings/endpoints/dependencies.py:14,41,44`; `infrastructure/background_tasks/request_expiry_job.py:8-10,52`; route descriptions `booking_requests.py:70,100`; the comment at `config/settings.py:168`; the contract "Notifications import nothing from bookings" in `pyproject.toml:151-156` goes with the package's endpoints, or its comment is fixed if the package stays as the email home.
- Also: `backend/uv.lock`; `tests/test_assistant_turn.py:579-592` (the direct `get_chat_model` test becomes a `build_chat_model` test); `tests/test_assistant_actions.py:51` (`DONE_FIXED` becomes "Done."); `tests/test_settings.py:12,33`, `.env.example:5,8`; `core/health/schemas/health.py:11`, `schemas/__init__.py`, `endpoints/health.py:3,11-17`, `tests/test_health.py:103-107`; `scripts/seed_menu.py:18-25`; `booking_schedule.py:120-122` (`check_requestable_start`), `booking_service.py:143-155` (where the expected check goes); `booking_request_service.py:53,88-90,127,162-166`, `request_expiry_service.py:5-8,28`, `booking_participant_repository.py:72-81`; the propose copies `booking_tools.py:187-198,245-262,278-285`, `preorder_tools.py:251-253`; `README.md`/`README.uk.md` gain an ADR 21 row.
- Tests: `tests/test_notifications.py` — the route tests go, the email tests stay without `stored_notifications` (rename the file to `test_decision_emails.py` and the two tests that mention notifications); `tests/test_request_expiry.py:37-38,47,142-150` and the assertions on stored notifications; the retry test at `:322-331` fails through `DecisionNoticeBuilder.build` instead; the `NotificationKind` import and `REJECTED` at `:36,55` go; `test_openapi.py:72-77` (the Notifications block and `("get", "/")`); `test_database.py:1005-1042` (replace by absence); `test_grafana_reader_migration.py:87` (the denied `notifications` query goes).
- `backend/migrations/versions/0025_drop_notifications.py` (`down_revision` "0024"), reusing 0019's columns, indexes and FKs in the downgrade.
- Search: `core/bookings/services/table_search_service.py:87-93`, `booking_schedule.py:52-60` (`is_free`) and `:111-113` (`check_requestable_start`); `booking_service.py:63-64`.
- Edit: `booking_service.py:120-168`, `core/bookings/ai_tools/booking_edit_applier.py:20-40`.
- Apply text: `assistant/services/assistant_apply_service.py:38,161-164`.
- Model: `main.py` (`create_app`, lifespan), `assistant/endpoints/dependencies.py` (`get_chat_model`); `openai.DefaultAsyncHttpxClient`; add `openai` as a direct dependency; langchain-openai otherwise shares a process-wide cached httpx client that must not be closed.
- Unused: `config/settings.py:25`, `.env.example:8`; `core/health/endpoints/health.py:11` and its test; `pyproject.toml` dev group; `core/menu/services/dish_seed_service.py:61`, `repositories/dish_repository.py:59`, `scripts/seed_menu.py`, `tests/test_seed_menu.py`; `core/auth/services/session_service.py:88`, `verification_code_service.py:85`, `core/bookings/services/participant_service.py:233`; `common/ai_tools.py` and the propose code in `core/bookings/ai_tools/booking_tools.py` and `preorder/ai_tools/preorder_tools.py:251`.
- Docs: new `docs/adr/0021-decisions-by-email-only.md`; `docs/adr/0018-in-app-notifications.md` status; `docs/adr/0013-…` lock order text; `README.md:105`, `README.uk.md:105`; `docs/roadmap.md:12,22,145`; mentions in ADR 14 and ADR 19 updated in one sentence each.

## Tasks & Acceptance

**Execution:**
- [x] Tests first: the matrix rows, the trimmed email tests, the absence checks -- contract.
- [x] Notifications removal and migration 0025; recipient lock removal -- behaviour.
- [x] Search rule, edit with expected values, apply text, one chat model -- behaviour.
- [x] Unused and duplicated code removed -- behaviour.
- [x] ADR 21, ADR 18 and 13 amendments, README, roadmap -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean; `alembic check` is clean at 0025.
- Given the local API, when staff rejects a request through the API, then the decision email is logged (email off) and `GET /api/v1/notifications` answers 404; a search for six people today hides the starts inside the request lead.

## Implementation Notes

- 2026-11-18: implemented by a subagent in the worktree `.claude/worktrees/backend-cleanup`; the deleted files were removed with `rm` as the spec lists (Vlad decided the removal). After the review patches 912 tests, ruff, format check, mypy (353 files), 11 import contracts and `alembic check` at 0025 (on `app_test`) clean. The flaky `test_the_sweep_skips_a_request_locked_by_a_concurrent_decision` passed 20 of 20 alone and 5 of 5 with its file at a quiet moment: its two failures came from another process using the shared `app_test`.
- 2026-11-19 00:37 Tbilisi, live, parent session: the worktree API on port 8011 with the worktree's `.env`, on the shared local `app` left at 0024 (the code no longer reads the notifications table, and Vlad's main checkout still uses it): `/health` ok, `GET /` and `GET /api/v1/notifications` 404, OpenAPI title "backend-showcase" with no notification or root paths. With `BOOKING_AUTO_REJECT_LEAD_MINUTES=720` the search for today showed parties of 4 from 10:00 (20 tables) and parties of 6 only from 13:00 (14 tables). Two assistant turns on the shared chat model streamed `thinking`, `chunk`, `done` and named the two $8 desserts. The decision email is covered by `test_decision_emails.py` (no local staff password for a live reject). The menu seed was not run against a bucket; its tests pin the behaviour, and the developer's 30 pictures already match the image keys.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Code review: an unsupported picture suffix fails mid-upload; an empty dishes table succeeds silently (edge-case, blind) | medium | the content type is looked up inside the loop | patch: both checked in the first pass |
| Code review: the missing-picture test removes the first picture; `.webp`/`.png` untested (verification-gap, blind) | medium | slug order makes the missing file the first one visited | patch: last key, new cases |
| Code review: the seed now needs pictures named after the image key (edge-case, blind) | low | the developer's 30 pictures are already named `<slug>.jpg`, checked 2026-11-18 | patch: usage text only |
| Code review: `test_the_sweep_skips_a_request_locked_by_a_concurrent_decision` failed twice (verification-gap) | maybe-false | passed 17 of 19 runs; could be the shared `app_test` or the lock removal | patch: investigate |
| Code review: tomorrow and edit-slots rows untested (blind) | low | | patch: tests |
| Code review: ADR 20 describes the edit comparison in the applier (blind) | low | it moved into `BookingService.edit` | patch |
| Code review: ADR 21 omits that 0025 deletes existing rows (blind) | low | | patch |
| Code review: README ADR 18 row not marked superseded (blind) | low | | patch |
| Code review: `.gitignore` comment names `dishes.json` (blind) | low | | patch |
| Code review: `get_chat_model` would 500 on an app built without `create_app` (edge-case) | false | every app is built by `create_app` | rejected |
| Code review: the 503 gate and the model come from two sources (blind) | low | both read the same environment in every deployment; tests override the model | rejected: the spec keeps the gate on settings |
| Code review: "menu content changes only through migrations" not recorded (blind) | low | decided with migration 0007; the deferred entry on documenting the seeds stays | rejected |
| Code review: old stored hashes not checked end to end (blind) | low | the helper is byte-identical to the three copies and a test pins it against `hashlib` | rejected |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

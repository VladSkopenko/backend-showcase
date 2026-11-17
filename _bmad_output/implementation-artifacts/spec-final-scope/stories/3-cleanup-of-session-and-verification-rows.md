---
title: 'Cleanup of session and verification rows'
type: 'feature'
created: '2026-11-17'
status: 'in-review'
baseline_commit: 'f2014425c94b36cd7b8bdcd97b18e303f2cac5ba'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-final-scope/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/4-auto-reject-pending-requests.md'
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every login and refresh inserts a `refresh_tokens` row and every code request a `verification_codes` row, and nothing deletes them; dev gains hundreds of token rows a day from the simulator's logins.

**Approach:** A periodic cleanup task in the API process deletes `refresh_tokens` rows past their `expires_at`, and `verification_codes` rows that are expired, older than one day and not the newest code of their user and purpose. Rows that reuse detection, a rate limit or the verify answer still read stay.

## Boundaries & Constraints

**Always:**
- A refresh token is deleted only once `expires_at <= now`, revoked, rotated or not: until then a rotated token stays, so presenting it again still revokes every active session of the user. Accepted change: an expired rotated token presented after a run no longer triggers that mass revocation; it answers `SESSION_INVALID` and leaves the user's tokens alone.
- A verification code is deleted only when `expires_at <= now`, `created_at <= now - 1 day` (the daily window of the reset-code limit, `VerificationCodeService.DAILY_LIMIT_WINDOW`; the hourly limit and the resend cooldown look back less) and a newer code of the same user and purpose exists. The newest code always stays, so verify keeps answering `CODE_EXPIRED` for it, the answer the frontend restarts its timer on.
- Bulk `DELETE ... WHERE` statements in SQL, no rows loaded into Python. Core auth owns the deletes; the job only opens a session, calls them, commits, and logs one INFO line with both counts when it deleted rows.
- Neutral names, because story 4 adds chat sessions to the same job: `CleanupJob`, task name "cleanup", settings class `CleanupSettings` with prefix `CLEANUP_` and `interval_seconds` (`CLEANUP_INTERVAL_SECONDS`, default 3600, greater than 0), in `.env.example`.
- Runs on the existing `PeriodicTask` runner in the app lifespan beside request expiry: own session, one transaction per run, rolled back and logged on failure, the next run tries again.

**Never:** Deleting a token before `expires_at`; touching `users`, `oauth_accounts`, booking `guests` or any other table; a new worker process, Redis or a scheduler library; a migration.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Expired tokens | tokens past `expires_at`: active, revoked, rotated | all deleted | N/A |
| Live tokens | tokens before `expires_at`: active, revoked, rotated | all kept | N/A |
| Token boundary | `expires_at == now` | deleted | N/A |
| Reuse still caught | rotated token before `expires_at`, after a run | refresh with it revokes the user's active tokens, `SESSION_INVALID` | N/A |
| Expired rotated token | rotated token past `expires_at`, after a run | refresh answers `SESSION_INVALID`; the user's active tokens stay | N/A |
| Old codes | expired codes created more than a day ago, consumed or not, with a newer code of the same user and purpose | deleted | N/A |
| Newest code kept | the user's only, old and expired, code of a purpose | kept; verify with it answers `CODE_EXPIRED` | N/A |
| Recent codes | expired code created less than a day ago; unexpired code | kept, so the hourly and daily limits still count them | N/A |
| Code boundary | `created_at == now - 1 day`, expired, a newer one exists | deleted | N/A |
| Lifespan | app start and shutdown | the "cleanup" and "request expiry" tasks both start and stop | N/A |
| Failing run | the database errors mid-run | rolled back, logged; the next run works | error logged |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/auth/repositories/refresh_token_repository.py`, `verification_code_repository.py` -- add bulk deletes returning the row count; the code delete keeps the newest row per `(user_id, purpose)` with a `NOT`-newest condition (an `EXISTS` on a newer row).
- `backend/src/app/features/core/auth/services/` -- new cleanup service: both deletes for a given `now` (from `app.common.clock`), returns both counts; uses `VerificationCodeService.DAILY_LIMIT_WINDOW`.
- `backend/src/app/features/core/auth/services/session_service.py:42-80` -- refresh and logout treat a missing token as invalid; unchanged.
- `backend/src/app/features/core/auth/services/verification_code_service.py:68-80` -- verify reads only the newest code; unchanged.
- `backend/src/app/infrastructure/background_tasks/` -- `CleanupJob` beside `request_expiry_job.py` (same session, commit and rollback pattern); export it.
- `backend/src/app/main.py:60-77` -- the lifespan starts and stops a second `PeriodicTask` named "cleanup".
- `backend/src/app/config/settings.py` -- `CleanupSettings` added to `Settings`; `backend/.env.example` gets the line.
- `backend/tests/test_request_expiry.py:482-499` -- the lifespan test patches only `RequestExpiryJob.run`; it must patch `CleanupJob.run` too, or the real cleanup commits deletes in `app_test`. Move or extend it so both tasks are asserted.
- The app configures no logging (deferred-work), so the INFO line is checked with `caplog` in a test, not in a log.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_cleanup.py` -- one test per matrix row and the INFO line via `caplog`, written first and failing -- contract.
- [x] `backend/tests/test_settings.py`, `backend/tests/test_request_expiry.py` -- pin the new setting and its bound; the lifespan test patches both jobs -- pins.
- [x] Repository deletes, cleanup service, job, lifespan, settings, `.env.example` -- behaviour.
- [x] `docs/roadmap.md` -- tick the cleanup item -- record.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass, and ruff, mypy and `lint-imports` are clean.
- Given the local API with a short `CLEANUP_INTERVAL_SECONDS`, when it starts over a database with expired token rows and old codes, then within one interval read-only `SELECT` counts show those rows gone and unexpired tokens and each user's newest code kept.
- Given dev after deploy, when `Deploy dev` finishes, then it is green and `/health` answers ok. Refresh tokens live `TOKEN_REFRESH_TTL_DAYS` (30), so dev's first token rows, from about 2026-11-13, become deletable around 2026-12-13; until then dev's count keeps growing, and the deletion is shown on the local API.

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

## Implementation Notes

- 2026-11-17: implemented by a subagent from this spec.
- Deletes: `RefreshTokenRepository.delete_expired(now=)` (`expires_at <= now`) and `VerificationCodeRepository.delete_superseded(now=, created_at_or_before=)` (`expires_at <= now`, `created_at <= created_at_or_before`, `EXISTS` a row of the same `user_id` and `purpose` with a later `created_at`); both are ORM bulk `DELETE` with `synchronize_session=False` and return the cursor's row count. Two codes with the same `created_at` never supersede each other, so both stay.
- Service: `AuthCleanupService.delete_stale()` in `features/core/auth/services/auth_cleanup_service.py` reads `clock.now()`, passes `now - VerificationCodeService.DAILY_LIMIT_WINDOW` as `created_at_or_before`, returns the `DeletedAuthRows` dto (`refresh_tokens`, `verification_codes`).
- Job: `CleanupJob(sessionmaker)` in `infrastructure/background_tasks/cleanup_job.py`, same session, commit and rollback pattern as `RequestExpiryJob`; INFO line "Deleted N expired refresh tokens and M old verification codes" only when either count is non-zero. `main.py` starts the "cleanup" task after "request expiry" and stops it first.
- Settings: `CleanupSettings.interval_seconds` (`CLEANUP_INTERVAL_SECONDS`, default 3600, `gt=0`) as `Settings.cleanup`; `CLEANUP_` added to the prefixes `tests/conftest.py` clears.
- Tests: `tests/test_cleanup.py`, 15 tests (one per matrix row, the INFO line, logout with an expired rotated token, the code `expires_at == now` boundary, two codes with the same `created_at`). The failing-run test calls `job.run()` directly twice; the runner retry and logging stay covered in `test_request_expiry.py`. The lifespan test moved there from `test_request_expiry.py` and patches both `CleanupJob.run` and `RequestExpiryJob.run`. Full suite before the review fixes: 761 passed; ruff, format check, mypy, 10 import contracts clean.
- Live check, local API on `app` at 0019 (port 8010) with `CLEANUP_INTERVAL_SECONDS=15`, `TOKEN_REFRESH_TTL_DAYS=0` (new tokens expire at once) and `EMAIL_USERNAME=` (emails only logged): registered and verified `cleanup-check@example.com` and logged in (2 expired tokens), requested a password reset for `reset-1794229060@example.com`, whose only reset code was from 2026-11-09. Before the run: 101 tokens (2 expired), 23 codes (1 deletable). 20 s later: 99 tokens (0 expired, the check user has none), 22 codes over 22 user-purpose pairs, the old reset code gone and the new one kept, the same user's single 2026-11-09 email code kept. SIGINT logged "Application shutdown complete". The INFO line does not show in uvicorn output (no logging config); it is covered by the `caplog` test.

- 2026-11-17, parent session after the review patches: 764 tests, ruff, format check, mypy and 10 import contracts clean. Live, local API on port 8010 with `CLEANUP_INTERVAL_SECONDS=15`, `TOKEN_REFRESH_TTL_DAYS=0` and email off: registered, verified and logged in `live3-…@example.com` through the API; read-only counts went from 101 tokens (2 expired) to 99 (0 expired) 11 s later. Codes stayed 23 on 23 user-purpose pairs: the earlier run had already removed the superseded ones, so this run showed no code deletion; the tests cover it.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence | Route |
|---|---|---|---|
| Deleting the newest code turns `CODE_EXPIRED` into `CODE_INVALID`, which the frontend branches on | high | `verification_code_service.py:71-79`; `VerifyEmail.tsx:63`, `ResetPasswordModal.tsx:112,131` | patch: keep the newest code per user and purpose |
| Expired rotated token no longer triggers mass revocation after deletion | medium | `session_service.py:49-52`, `:64-66` | patch: stated as accepted change, matrix row |
| "Log shows the counts" and "/health shows the task" cannot be checked | medium | no logging setup in `src`; `/health` reports only the database | patch: `caplog` test, SELECT counts locally, dev limited to a green deploy |
| Existing lifespan test would run the real cleanup in `app_test` | medium | `test_request_expiry.py:482-499` patches only `RequestExpiryJob.run` | patch: patch both, matrix row |
| "auth cleanup" names do not fit story 4 | low | `assistant.md` History | patch: `CleanupJob`, `CLEANUP_INTERVAL_SECONDS` |
| Umbrella success signal "count stops growing" not met at merge | low | refresh TTL 30 days | patch: SPEC.md success signal reworded |
| Update `deferred-work.md` entries this story closes | false | the file is append-only: existing entries are never modified | rejected |
| No boundary row for codes | low | `verification_code_repository.py:38` counts `created_at > since` | patch: matrix row |
| Code review: logout with a deleted expired rotated token also skips mass revocation, untested (blind) | low | `session_service.py:58-69` returns on a missing token | patch: test; covered by the accepted change |
| Code review: the live-rotated-token test passes with an empty job (blind) | medium | nothing in its setup was expired | patch: expired token added and asserted deleted |
| Code review: same-`created_at` codes not pinned (blind) | low | strict `>` in the `EXISTS` | patch: test |
| Code review: code `expires_at <= now` boundary untested (blind) | low | only the token boundary was tested | patch: test |
| Code review: failing-run test drives `PeriodicTask` on the shared connection (blind) | medium | its own comment flags the risk | patch: direct `job.run()` with `pytest.raises` |
| Code review: `created_by` parameter name misleads (blind) | low | it is an inclusive `created_at` bound | patch: `created_at_or_before` |
| Code review: `.env.example` and settings comments misdescribe what is deleted (blind) | low | "session rows", "no limit counts" | patch |
| Code review: lifespan interval wiring untested (blind, verification-gap) | medium | the lifespan test asserts only task names; request expiry has the same gap | defer: deferred-work entry for both tasks |
| Code review: expired rotated token loses mass revocation (edge-case) | false | the accepted change in the frozen block | rejected |
| Code review: lifespan test moved out of `test_request_expiry.py` (edge-case) | false | the spec allows moving or extending it | rejected |

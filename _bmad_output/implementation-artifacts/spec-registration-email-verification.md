---
title: 'Registration with email verification by code'
type: 'feature'
created: '2026-11-04'
status: 'done'
baseline_commit: 'f23262ba562b1de19727eb4e0680652d46c9e98d'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-database-foundation.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Guests cannot create an account. The Figma "Create an account" modal asks for first name, last name, email, password and its confirmation, then a 6-digit code from email.

**Approach:** `POST /auth/register` creates an unverified user and emails a code; `POST /auth/verify-email` confirms it and sets `email_verified_at`; `POST /auth/resend-code` sends a fresh code. Mail goes through Gmail SMTP as a styled HTML email. Story 2 of 5 on `feature/database`; no session is issued here (login is story 3).

## Boundaries & Constraints

**Always:**
- `User.name` becomes `first_name` and `last_name` (required, ≤100 each) by editing the unmerged migration 0001 (Vlad: unmerged migrations may be edited, merged ones never).
- Email is trimmed and lowercased where it is written and looked up.
- Decision (Vlad): the only password rule is a minimum length of 8; any further rules shown in the design are enforced by the frontend.
- Decision (Vlad): `AppSettings.environment` (`APP_ENVIRONMENT`: `local`, `dev`, `staging`, `prod`; default `local`) distinguishes environments; deploy sets it from `APP_ENV`. In `local` only, register and resend responses also carry `debug_code` (a separate field omitted from the JSON when unset) with the plain code so local testing needs no inbox; the email is still sent when configured. In `dev`, `staging` and `prod` the field is absent, because those are reachable from the internet.
- Passwords hashed with `pwdlib` Argon2 (passlib is unmaintained); plain passwords and codes are never stored or logged.
- Codes: 6 digits from `secrets`, stored hashed (SHA-256) in a `verification_codes` table with `purpose` (enum `EMAIL_VERIFICATION`; story 4 adds `PASSWORD_RESET`), `expires_at`, `attempts`, `consumed_at`. A new code invalidates the previous unconsumed one of the same purpose.
- TTL 10 minutes, resend cooldown 60 s, 5 wrong attempts invalidate a code, at most 5 codes per user per hour: `AuthSettings` (`AUTH_` prefix) fields `verification_code_ttl_minutes`, `resend_cooldown_seconds`, `max_code_attempts`, `max_codes_per_hour` with these defaults.
- Decision (Vlad): registration is complete only when the email is verified. An unverified user never blocks an address: registering an unverified email again replaces the names and password and sends a new code (cooldown and hourly limit apply). `EMAIL_TAKEN` is only for verified users. Story 3 makes a successful `verify-email` return access and refresh tokens.
- `EmailSettings` (`EMAIL_` prefix) fields `smtp_host` (`smtp.gmail.com`), `smtp_port` (587, STARTTLS), `username`, `password` (`SecretStr`), `sender`. An empty or missing username means unconfigured: in `local` the email is logged without the code; in any other environment the send logs an error without the code and does not raise. `AppSettings` gains `frontend_url` (default `https://family-rest.vercel.app`).
- Every settings class sets `extra="ignore"`, because a shared `.env` holds other prefixes' keys. `tests/conftest.py` disables `.env` loading so a developer's `backend/.env` never changes test behaviour or sends mail.
- Decision (Vlad): every settings class also reads `backend/.env` when it exists (local only; containers get real environment variables, and the image has no `.env`). `backend/.env.example` lists every variable with its default or an empty value; `.env` stays gitignored and is never read by agents.
- The email is sent after the transaction commits (FastAPI background task scheduled by the endpoint), so a rolled-back registration never mails a code.
- Decision (Vlad): the HTML email's main action is a "Confirm email" button to `{frontend_url}/verify-email?email=…&code=…` (nothing to copy); the code is also shown in a large letter-spaced block for manual entry. Table layout, inline CSS, plain-text part, rendered with Jinja2. The frontend needs a `/verify-email` page that posts both values.
- Decision (Vlad, during review): object-oriented style like `app/infrastructure/email`. Repositories are classes holding the session (`UserRepository(session)`, `VerificationCodeRepository(session)`); services are classes with constructor-injected dependencies (`RegistrationService`, `EmailVerificationService` with `verify` and `resend`, `VerificationCodeService`, `PasswordHasher`, `VerificationEmailRenderer`); endpoints build them through FastAPI dependencies. One class per file, keyword-only arguments on public methods, short docstrings. Generic stateless helpers are plain functions in `app/common` (the clock moves to `app/common/clock.py`). Enums live in a feature-level `enums/` package, separate from `models/` and `schemas/`. Service dataclasses live in a feature-level `dto/` package; `services/` holds only service classes and `exceptions.py`, which also owns `CODE_INVALID` and `CODE_EXPIRED`; import-linter keeps `dto` and `enums` free of HTTP and `dto` free of `schemas`.
- Errors are domain exceptions with a stable `code`, translated to JSON `{"code", "message"}` (plus optional `retry_after`, mirrored in a `Retry-After` header) by one handler registered in `main.py`; the HTTP status per exception class comes from a mapping in the auth endpoints package (settles the deferred "where domain exceptions live" item: base in `app/common/errors.py`).
- A wrong code is an expected outcome, not an exception: the verify service returns a result (verified / invalid / expired) and the endpoint builds the 400, so the `attempts` increment commits instead of being rolled back by `get_session`.
- Concurrency: verify and resend lock the user row (`SELECT … FOR UPDATE`) and increment `attempts` atomically; a unique violation on `uq_users_email` during register maps to `EMAIL_TAKEN`.
- Timestamps that the logic compares (`created_at`, `expires_at`, `consumed_at` of codes, `email_verified_at`) are set from the service clock, not the database `now()`, so tests can move time.
- Argon2 hashing and verification run in a worker thread (`anyio.to_thread.run_sync`).
- Email link: query values URL-encoded; Jinja2 with autoescape, templates loaded from the package (`PackageLoader`), never relative to the working directory.

**Never:** sessions, login, password reset, OAuth; phone; storing plain codes; sending mail inside the request transaction.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Register | valid fields, new email | 201 with user id and email; code emailed; `debug_code` only in local | N/A |
| Email taken | email of a verified user (case-insensitive) | 409 `EMAIL_TAKEN` | no email sent |
| Re-register unverified | email of an unverified user, last code ≥ 60 s old | 201; names and password replaced; new code emailed, old one invalid | N/A |
| Re-register too soon | email of an unverified user, last code < 60 s old | 429 `RESEND_TOO_SOON` with `retry_after`; nothing changed | N/A |
| Hourly code limit | 6th code for one user within 60 minutes (register or resend) | 429 `RESEND_TOO_SOON` with `retry_after` until the oldest of those codes leaves the window | N/A |
| Bad input | passwords differ, password < 8 chars, malformed email, empty names | 422 | N/A |
| Verify | correct unexpired code | 200; `email_verified_at` set; code consumed | N/A |
| Wrong code | wrong code | 400 `CODE_INVALID`; attempts +1; 5th wrong attempt invalidates the code | N/A |
| Expired code | correct code after 10 min | 400 `CODE_EXPIRED` | N/A |
| Already verified | verify or resend for a verified email | 409 `ALREADY_VERIFIED` | N/A |
| Resend | unverified user, last code ≥ 60 s old | 202; new code emailed; old one invalid; `debug_code` only in local | N/A |
| Deployed response | register or resend with `APP_ENVIRONMENT` `dev`, `staging` or `prod` | no `debug_code` in the body | N/A |
| Resend too soon | < 60 s since last code | 429 `RESEND_TOO_SOON` with `retry_after` seconds | N/A |
| Unknown email | verify or resend for no user | 404 `USER_NOT_FOUND` | N/A |

</frozen-after-approval>


## Code Map

- `backend/src/app/features/core/users/models/user.py`, `backend/migrations/versions/0001_create_users.py` -- replace `name` with `first_name`, `last_name`.
- `backend/src/app/common/database.py` -- `get_session`; endpoints use `Depends(get_session, scope="function")`, so the commit precedes the response and background tasks.
- `backend/src/app/config/settings.py` -- domain classes; add `AuthSettings`, `EmailSettings`, `AppSettings.frontend_url`.
- `backend/src/app/model_registry.py` -- register the new model.
- `backend/tests/conftest.py` -- `session_factory` fixture patches `get_sessionmaker`; reuse for API tests with `httpx2.AsyncClient` + `httpx2.ASGITransport` (the dev dependency is `httpx2`, module `httpx2`).
- `backend/pyproject.toml` -- import-linter contracts stay as they are: `app.infrastructure.email` triggers no contract change (only `background_tasks` would).
- `deploy/app/compose.yml`, `.github/workflows/delivery.yml` -- secrets piped as `KEY=value` lines; api `environment` passes them on.
- `_bmad_output/implementation-artifacts/deferred-work.md` -- email normalisation and domain-exception items are settled by this story.

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- `uv add "pwdlib[argon2]" aiosmtplib jinja2 "pydantic[email]"`.
- [x] `backend/tests/test_database.py` -- replace `name` with `first_name`/`last_name` in fixtures and the column map.
- [x] `backend/tests/test_registration.py` -- every matrix row through the HTTP API with a fake email sender capturing messages; time controlled by patching the service clock.
- [x] `backend/tests/test_verification_email.py` -- rendered HTML contains the code and the prefilled link; text part contains the code.
- [x] `backend/src/app/features/core/users/models/user.py`, `migrations/versions/0001_create_users.py` -- `first_name`, `last_name`.
- [x] `backend/src/app/features/core/users/repositories/user_repository.py` -- get by email, add.
- [x] `backend/src/app/common/errors.py` -- `DomainError(code, message)`.
- [x] `backend/src/app/features/core/auth/` -- `models/verification_code.py`, `repositories/verification_code_repository.py`, `services/` (registration, verification, resend, password hashing, code generation, clock), `services/exceptions.py`, `schemas/`, `endpoints/` (router with the three routes, background email task, error status mapping), `templates/verification_email.html` and `.txt`.
- [x] `backend/src/app/infrastructure/email/sender.py` -- `EmailSender` protocol, SMTP implementation with aiosmtplib, logging implementation when unconfigured; endpoint dependency selects it from settings.
- [x] `backend/migrations/versions/0002_create_verification_codes.py` -- the unmerged revision 0002, renamed from `0002_add_verification_timestamps.py` (keep its id); add the `verification_codes` table and its enum (uppercase labels per backend.md); downgrade drops the table and then the enum type explicitly, or the CI round-trip fails on the second upgrade.
- [x] `backend/src/app/config/settings.py`, `backend/src/app/main.py`, `backend/src/app/model_registry.py` -- settings classes, router and error handler registration, model registration.
- [x] `backend/.env.example` -- every `APP_`, `DATABASE_`, `EMAIL_`, `AUTH_` variable with defaults; replaces Vlad's untracked `backend/env.example` once he agrees to delete it.
- [x] `deploy/app/compose.yml`, `.github/workflows/delivery.yml` -- `APP_ENVIRONMENT: ${APP_ENV}` for `api`; `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_SENDER` from the `dev` Environment secrets, piped on stdin and passed to `api`.
- [x] `_bmad_output/implementation-artifacts/deferred-work.md` -- nothing new unless review defers.

**Acceptance Criteria:**
- Given a deploy with the `dev` email secrets set, when a guest registers through the API, then a styled email with the code arrives in the inbox, and verifying with it sets `email_verified_at`.
- Given CI, then lint, mypy, import-linter, migration round-trip with `alembic check`, and tests pass.

## Design Notes

- Gmail SMTP needs 2-step verification and an app password on the sending account; the sender address must be that Gmail address.
- `verification_codes` is generic so story 4 (password reset) reuses it with a new enum member in its own migration.

## Verification

**Commands:**
- Vlad approved recreating the local database once, because 0001 and 0002 change: `cd backend && docker compose down -v`, then
- `cd backend && docker compose up -d --wait && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest && uv run alembic check` -- all pass.
- `actionlint .github/workflows/*.yml` and `docker compose -f deploy/app/compose.yml config --quiet` with the variables set -- clean.

## Implementation Notes

- A new code invalidates earlier ones by being the latest: verify and resend read only the newest code of the user and purpose (`get_latest`), so older rows need no update.
- The root `Settings` reads only init values (`settings_customise_sources`); each block reads its own prefix and `backend/.env`. Otherwise a shell variable such as `EMAIL` is parsed as the whole `email` block and crashes startup.
- `domain_error_response` (status lookup along the MRO, 500 fallback, JSON body and `Retry-After`) lives in `app/common/error_responses.py`, apart from `DomainError`; the global handler and the verify endpoint both use it. It is kept apart because services import `app.common.errors` and the HTTP contract forbids fastapi even indirectly.
- `backend/env.example` (untracked) is left in place for Vlad to delete.
- `VerificationCodeService.issue` enforces the cooldown and the hourly limit itself, so register, re-register and resend cannot skip them. When both apply, `retry_after` is the later of the two. Re-registration issues the code before replacing names and password, so a refused code leaves the user untouched.
- Services receive the session and build their repositories in the constructor; the other collaborators (`PasswordHasher`, `VerificationCodeService`) are injected. Endpoint providers cannot construct repositories, because the import contract forbids endpoints from importing them. FastAPI caches `get_session` per request, so every service shares one session.
- The local database was not recreated (`docker compose down -v` was denied by the permission system); verification ran against a throwaway `postgres:18` container on port 5439.

## Spec Change Log

- 2026-11-04, during review: Vlad decided that an unverified user never blocks an email (re-registration replaces it) and approved a limit of 5 codes per user per hour; migration 0002 renamed to match its content. KEEP: the OOP layout, dto/enums split, all review fixes.

- 2026-11-04, during review: Vlad asked to replace function-based repositories and services with classes, move the clock to `app/common`, and keep enums in `enums/`. Behaviour and API unchanged. KEEP: every test's behaviour, the review patches, the result-instead-of-raise for wrong codes.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | blind, edge | Unmapped `DomainError` subclass raises `KeyError` in the handler | medium | `ERROR_STATUSES[type(exc)]` in `main.py`. Patch: MRO lookup, 500 fallback. |
| 2 | edge | No max length on passwords; huge payloads Argon2-hashed | medium | `Field(min_length=8)` only. Patch: `max_length=128` on both fields. |
| 3 | edge | `AUTH_*` accepts zero or negatives | low | Operator misconfiguration only. Rejected. |
| 4 | blind, edge, verification-gap | Exported `APP_`/`EMAIL_`/`AUTH_` shell vars reach tests; one test could send real mail | medium | conftest disables only the env file. Patch: autouse fixture deleting those prefixes. |
| 5 | verification-gap | Configured SMTP path never exercised | medium | No test touches `SmtpEmailSender` or `aiosmtplib`. Patch: test with a captured `aiosmtplib.send`. |
| 6 | verification-gap | `APP_ENVIRONMENT`, `EMAIL_*`, `AUTH_*` env mapping untested; stray `EMAIL=x` | medium | A key mismatch would leave deployed apps on `local` and expose `debug_code`. Patch: extend settings tests. |
| 7 | verification-gap | Verify response body only partly asserted | low | Only `email` checked. Patch: assert the full body. |
| 8 | verification-gap | Swallow-and-log on a failing send untested | low | Removing the try/except passes. Patch: failing-sender test. |
| 9 | blind, edge | Username set but sender or password empty selects SMTP and fails every send | low | `get_email_sender` checks username only. Patch: require all three. |
| 10 | blind | Resend test skips the invalidation check when codes collide | low | `if old_code != new_code`. Patch: fixed code sequence. |
| 11 | blind | Root `Settings.model_config` `env_file` has no effect | low | Sources return only `init_settings`. Patch: drop the misleading config. |
| 12 | blind | No index or `ondelete` on `verification_codes.user_id`, rows never cleaned | low | No consumer deletes users yet. Defer. |
| 13 | blind, edge | Resend cooldown is the only cap: ~7,200 guesses a day, Gmail quota | medium | Each code resets attempts. Asked Vlad (fix not settled by the spec). |
| 14 | blind | Unverified accounts block the real owner forever | medium | Matches the spec; no reclaim path. Defer. |
| 15 | verification-gap | Row lock in verify/resend untested | medium | Shared-connection harness cannot observe locks. Defer (needs a two-connection fixture). |
| 16 | blind | Error contract, result-instead-of-raise and the migration rule have no ADR | low | workflow.md rule 5. Defer: one ADR after the auth stories. |
| 17 | blind | 422 body shape differs from `{"code","message"}` | medium | Frontend parses two shapes. Defer: decide with the ADR. |
| 18 | blind | Error responses missing from OpenAPI | low | Defer. |
| 19 | blind | Full email addresses in logs | low | Defer: mask with the logging stack (Phase 4). |
| 20 | blind | `0002_add_verification_timestamps.py` name no longer matches content | low | Asked Vlad about renaming. |
| 21 | blind | Duplicate `backend/env.example` | false | Not part of this change; Vlad's file, decision pending. |
| 22 | edge | `APP_ENVIRONMENT` defaults to `local` | low | Frozen decision; compose always sets it and #6 tests the mapping. Rejected. |
| 23 | edge | Removed deferred entry on `lower(email)` | false | Normalisation now happens on every ORM write and lookup; no Core writes exist. |

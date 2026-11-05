---
title: 'Login and JWT sessions in cookies'
type: 'feature'
created: '2026-11-05'
status: 'done'
baseline_commit: 'fc9135d9148b7e15d5e998c8623fff68fbaecb5c'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-registration-email-verification.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A verified user cannot sign in, and no endpoint knows who is calling.

**Approach:** Password login issues a 15-minute HS256 access JWT and a 30-day rotating refresh token, both in HttpOnly cookies; a successful email verification signs the user in the same way. Story 3 of 5 on `feature/auth`; all API routes move under `/api/v1`.

## Boundaries & Constraints

**Always:**
- Decision (Vlad): every API route lives under `/api/v1` (`/api/v1/auth/register`, `/verify-email`, `/resend-code`, `/login`, `/refresh`, `/logout`, `/me`). `/health` and `GET /` stay at the root: they are the deploy gate and the alerting probe, not API.
- Decision (Vlad): the frontend's Next.js rewrite keeps the path (`/api/v1/:path*` → `https://<api-host>/api/v1/:path*`), so a cookie `Path` set by the API matches what the browser sees.
- Access token: JWT HS256 via PyJWT, claims `sub` (user id as a string), `iat`, `exp` only, TTL 15 minutes. `TokenSettings` (`TOKEN_` prefix): `secret_key: SecretStr` required, no default, at least 32 characters (a shorter key fails at startup); `access_ttl_minutes=15`, `refresh_ttl_days=30`, `refresh_cookie_path="/api/v1/auth"`.
- Refresh token: `secrets.token_urlsafe(32)`, stored only as its SHA-256 hash with `expires_at`, `revoked_at` and `rotated_at`; every refresh revokes the presented token, marks it rotated and issues a new pair. Decision (Vlad, during review): only a token revoked by rotation counts as reuse: presenting it to refresh or logout revokes every active refresh token of that user (no grace window). A token revoked by logout or by a mass revocation just gets 401 on refresh (or 204 on logout) and revokes nothing else, so a stale device or a lost logout response does not log out newer sessions. Refresh and logout lock the user row (`FOR UPDATE`) before reading the token, so a concurrent rotation cannot slip a new token past a mass revocation.
- Cookies `access_token` (`Path=/`, `Max-Age` 15 min) and `refresh_token` (`Path=/api/v1/auth`, `Max-Age` 30 days): `HttpOnly`, `Secure`, `SameSite=Lax`, no `Domain` (AD-19). Clearing repeats each cookie's `Path`, `Secure`, `HttpOnly` and `SameSite` with `Max-Age=0`, and happens only when the request carried at least one of the two cookies. Tokens never appear in a response body.
- Access tokens are not revocable: one stays valid until its `exp` after logout or reuse revocation (at most 15 minutes).
- Lockout: 5 consecutive wrong passwords lock login for 5 minutes; while locked even the correct password gets 423 `ACCOUNT_LOCKED` with the message "Too many failed attempts. Try again in 5 minutes." (minutes from settings, no `retry_after`). Locking sets `login_locked_until` and resets `failed_login_attempts` to 0, so 5 attempts are available after it expires. Any correct password (including the 403 unverified case) resets the counter. The lock never affects refresh, logout, me or existing sessions. `AuthSettings` gains `max_login_attempts=5` and `login_lockout_minutes=5`.
- A wrong password, a failed refresh and reuse detection are returned as results, not raised, so counter increments and revocations commit (same pattern as `verify`), and the handler can clear cookies on the response it returns. Login locks the user row (`FOR UPDATE`).
- Unknown email and a user without a password hash get the same 401 `INVALID_CREDENTIALS` as a wrong password. The verified check runs after the password check: correct password on an unverified email → 403 `EMAIL_NOT_VERIFIED`; wrong password → 401 and counted.
- Decision (Vlad): `TOKEN_SECRET_KEY` lives in each GitHub Environment and reaches the VM `.env` over SSH stdin like `POSTGRES_PASSWORD`; the agent writes this PR's compose and workflow changes.
- JWT `iat`/`exp` and every lockout or expiry comparison use `app.common.clock`, so tests move time.

**Never:** password reset, OAuth, logout-everywhere endpoint, IP rate limiting, CSRF tokens, tokens in the body or `Authorization` header, python-jose, changes to re-registration (the pre-hijack question is Vlad's, outside this story), changes to Vlad's uncommitted health files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Login | verified user, correct password | 200 profile (`id`, `email`, `first_name`, `last_name`, `email_verified_at`); both cookies set; counter reset | N/A |
| Wrong password | verified user | 401 `INVALID_CREDENTIALS`; counter +1 | N/A |
| Fifth wrong password | 4 failures already | 423 `ACCOUNT_LOCKED`; locked for 5 minutes; counter 0 | N/A |
| Locked | within 5 minutes of the lock, any password | 423 `ACCOUNT_LOCKED`; counter unchanged | N/A |
| Lock expired, correct | 5 minutes later, correct password | 200 | N/A |
| Lock expired, wrong | 5 minutes later, wrong password | 401 `INVALID_CREDENTIALS`; counter 1 | N/A |
| Locked user refreshes | lock active, valid refresh cookie | 204; rotation works | N/A |
| Unknown email | no such user | 401 `INVALID_CREDENTIALS` | N/A |
| Unverified | correct password | 403 `EMAIL_NOT_VERIFIED`; no cookies; counter reset | N/A |
| Verify email | correct code | 200 as before, plus both cookies | N/A |
| Me | valid access cookie | 200 profile | N/A |
| Me without session | missing, malformed, bad signature, non-UUID `sub`, expired (16 min) access cookie, or deleted user | 401 `NOT_AUTHENTICATED` | N/A |
| Me after logout | access cookie copied before logout, within 15 min | 200 | N/A |
| Refresh | valid refresh cookie | 204; new pair of cookies; old refresh revoked | N/A |
| Refresh invalid | unknown or expired refresh cookie | 401 `SESSION_INVALID`; both cookies cleared | N/A |
| Refresh without cookies | no cookies | 401 `SESSION_INVALID`; no `Set-Cookie` | N/A |
| Refresh reuse | refresh token already revoked by rotation | 401 `SESSION_INVALID`; all user's refresh tokens revoked; cookies cleared | revocation commits |
| Refresh with a logged-out token | refresh token revoked by logout or mass revocation | 401 `SESSION_INVALID`; cookies cleared; no other token revoked | N/A |
| Logout | active refresh cookie | 204; token revoked; both cookies cleared | N/A |
| Logout with rotated token | refresh token already revoked by rotation | 204; all user's refresh tokens revoked; cookies cleared | N/A |
| Logout with a logged-out token | refresh token revoked by logout or mass revocation | 204; cookies cleared; no other token revoked | N/A |
| Logout without cookies | no cookies | 204; no `Set-Cookie` | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/main.py` -- mount `auth_router` with `prefix="/api/v1"`; health router untouched; `app = create_app()` builds settings at import.
- `backend/src/app/features/core/auth/endpoints/auth.py`, `dependencies.py`, `errors.py` -- current routes and providers; verify returns `domain_error_response(...)` for a failed outcome.
- `backend/src/app/common/error_responses.py` -- `domain_error_response` returns a `JSONResponse`; cookies must be cleared on that object.
- `backend/src/app/features/core/auth/services/email_verification_service.py`, `dto/verification_outcome.py` -- `verify` returns `VerificationOutcome(user, error)`; extend with the issued session.
- `backend/src/app/features/core/auth/services/verification_code_service.py` -- SHA-256 + `hmac.compare_digest` pattern to reuse for refresh hashes.
- `backend/src/app/features/core/auth/services/password_hasher.py` -- `verify(password=, password_hash=)`, already threaded.
- `backend/src/app/features/core/users/models/user.py`, `repositories/user_repository.py` -- add lockout columns; add `get_by_id(for_update=)`.
- `backend/src/app/model_registry.py` -- add `RefreshToken` to imports and `__all__`.
- `backend/src/app/config/settings.py` -- add `TokenSettings` to the root `Settings`; `AuthSettings` gains login limits.
- `backend/migrations/env.py` -- builds the full `Settings`, so alembic also needs `TOKEN_SECRET_KEY`.
- `backend/tests/conftest.py` -- clears `APP_`/`EMAIL_`/`AUTH_` env; test modules import `app.main` at collection.
- `backend/tests/test_registration.py` -- client uses `http://test` and `/auth/...` paths; `FakeClock` starts at 2026-11-04.
- `deploy/app/compose.yml` (api `environment`; `.env` values are unquoted, so secrets are hex), `.github/workflows/delivery.yml` (`deploy-dev` runs only on `main`, printf over stdin), `.github/workflows/ci.yml` (backend job runs alembic and pytest).
- `_bmad_output/planning-artifacts/architecture/architecture-backend-showcase-2026-10-28/ARCHITECTURE-SPINE.md` AD-19 -- frontend contract.

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- `uv add pyjwt`.
- [x] `backend/tests/conftest.py` -- set `os.environ["TOKEN_SECRET_KEY"]` unconditionally at module top to a 64-char hex test value; clear other `TOKEN_` variables.
- [x] `backend/tests/test_login.py` -- every matrix row through the HTTP API with `base_url="https://test"`; time via the fake clock; cookie attributes (set and clear) asserted from raw `Set-Cookie` headers.
- [x] `backend/tests/test_registration.py` -- new paths and base URL; verify sets both cookies.
- [x] `backend/tests/test_settings.py` -- `TOKEN_*` mapping, secret hidden in `repr`, missing and 31-char secrets fail.
- [x] `backend/tests/test_database.py` -- new `users` columns and `refresh_tokens` table.
- [x] `backend/src/app/config/settings.py` -- `TokenSettings`; `AuthSettings.max_login_attempts`, `login_lockout_minutes`.
- [x] `backend/src/app/features/core/users/models/user.py`, `repositories/user_repository.py` -- `failed_login_attempts` (int, server default 0), `login_locked_until` (nullable timestamptz); `get_by_id`.
- [x] `backend/src/app/features/core/auth/models/refresh_token.py`, `models/__init__.py`, `backend/src/app/model_registry.py` -- `refresh_tokens`: `id`, `user_id` FK `ondelete=CASCADE` indexed, `token_hash` unique, `expires_at`, `revoked_at`, `rotated_at`, `created_at`.
- [x] `backend/migrations/versions/0003_add_login_sessions.py` -- revision `0003`; columns and table; working downgrade.
- [x] `backend/src/app/features/core/auth/repositories/refresh_token_repository.py`, `repositories/__init__.py` -- get by hash, add, revoke all active for a user.
- [x] `backend/src/app/features/core/auth/services/` -- `access_token_codec.py`, `session_service.py` (`start`, `refresh`, `end`), `login_service.py`, `current_user_service.py`; new errors in `exceptions.py`; `email_verification_service.py` starts a session on success.
- [x] `backend/src/app/features/core/auth/dto/` -- `issued_session.py`, `login_outcome.py`, `refresh_outcome.py`, re-exported from `dto/__init__.py`.
- [x] `backend/src/app/features/core/auth/endpoints/` -- `cookies.py` (`SessionCookies`: `set(response, session)`, `clear(response)` on the response the handler returns), four routes, providers, `CurrentUserDep`, status map (401/403/423).
- [x] `backend/src/app/features/core/auth/schemas/auth.py` -- `LoginRequest` (`email`, `password` max 128), `UserResponse`.
- [x] `backend/src/app/main.py` -- `/api/v1` prefix.
- [x] `backend/.env.example` -- `TOKEN_*` (generate with `openssl rand -hex 32`) and new `AUTH_*` lines.
- [x] `deploy/app/compose.yml`, `.github/workflows/delivery.yml` -- `TOKEN_SECRET_KEY: ${TOKEN_SECRET_KEY:?...}` for `api`; secret piped on stdin from the `dev` Environment.
- [x] `.github/workflows/ci.yml` -- backend job env `TOKEN_SECRET_KEY` with a non-secret 64-char hex value.
- [x] `ARCHITECTURE-SPINE.md` AD-19 -- rewrite keeps the `/api/v1` path; cookie paths; refresh runs only in the browser behind a cross-tab lock (Web Locks API), never server-side; a lost refresh response means a global logout.

**Acceptance Criteria:**
- Given Vlad created `TOKEN_SECRET_KEY` (`openssl rand -hex 32`) in the `dev` Environment before the merge, when the PR merges to `main`, then login through the dev API sets both cookies and `GET /api/v1/auth/me` returns the profile.
- Given Vlad added `TOKEN_SECRET_KEY` to `backend/.env`, when the local live check runs, then register → verify → me → refresh → logout work through curl with a cookie jar.
- Given CI, then lint, mypy, import-linter, migration round-trip with `alembic check`, and tests pass.

## Design Notes

- Refresh tokens are 256-bit random, so a plain SHA-256 is enough; Argon2 is for low-entropy passwords.
- PyJWT 2.15 checks `exp` and `iat` against the real clock and rejects a non-string `sub`. Decode with `algorithms=["HS256"]`, `options={"verify_exp": False, "verify_iat": False, "require": ["sub", "iat", "exp"]}`; in the codec require integer `exp` and compare it with `clock.now()`, and map a non-UUID `sub` to `NOT_AUTHENTICATED`. Every `jwt.PyJWTError` maps to `NOT_AUTHENTICATED`.
- FastAPI drops headers set on an injected `Response` when the handler returns its own `Response` (routing.py, `isinstance(raw_response, Response)`), and exception handlers build fresh responses. Hence results instead of raises wherever cookies change, and `SessionCookies` writes to the returned object.
- Refresh order: hash lookup → lock user row → re-read the token with `FOR UPDATE` → decide. Two concurrent refreshes of one token serialise; the second is reuse.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest && uv run alembic check` -- all pass.
- `actionlint .github/workflows/*.yml` and `docker compose -f deploy/app/compose.yml config --quiet` with the variables set -- clean.

## Implementation Notes

- `CurrentUserDep` resolves to `UserResponse`, not the `User` model: the import contract forbids endpoints from importing models even for a type hint, so the provider maps the model returned by `CurrentUserService.get` to the schema. Another feature that needs the caller gets `id` and the profile fields from it.
- Outcomes keep the `VerificationOutcome` shape (`session` and `error`, both optional). Handlers check `error` first and narrow `session` with an `assert`, because mypy cannot tie the two fields together.
- Unknown email, a user without a password hash and an active lock raise instead of returning a result: nothing is written in those cases and no cookie changes.
- Refresh hashes are looked up by equality in SQL; `hmac.compare_digest` would only compare the hash with itself afterwards, so it is not used here.
- The re-read of the refresh token after locking the user uses `populate_existing`: `FOR UPDATE` alone returns the stale object from the identity map.
- `revoke_all_active` touches only tokens that are unrevoked and unexpired.
- A successful login leaves an expired `login_locked_until` in place; the comparison with the clock already ignores it.
- `delete_cookie` also writes `expires=<now>` next to `Max-Age=0`; browsers honour `Max-Age`.
- `Settings.token` carries `# type: ignore[arg-type]`: mypy sees the required `secret_key` constructor argument that pydantic-settings fills from the environment. `TokenSettings()` in `test_settings.py` carries `call-arg` for the same reason.
- Verification ran the full command list on the local database, and the CI-style migration round-trip plus the test suite on a throwaway `postgres:18` container on port 5439, so the local database was never downgraded. The live check ran against the local database with `TOKEN_SECRET_KEY`, `APP_ENVIRONMENT=local` and an empty `EMAIL_USERNAME` passed as process environment, so no `.env` was read and no mail went out; it left one user `live-<timestamp>@example.com` in the local database.

## Spec Change Log

- 2026-11-05, during code review: Vlad's rule for constants: one that belongs to a class becomes a class attribute, one that may need changing goes to settings. `TokenSettings` gains `algorithm` (`HS256` | `HS384` | `HS512`, default `HS256`) and `access_cookie_path` (default `/`); cookie names are `SessionCookies.ACCESS_NAME` / `REFRESH_NAME`; `HOURLY_LIMIT_WINDOW` is a `VerificationCodeService` attribute. Behaviour unchanged. KEEP: everything else.
- 2026-11-05, during code review (edge row 28): Vlad decided that only a token revoked by rotation counts as reuse; `rotated_at` added to `refresh_tokens` in the unmerged 0003. Known-bad state avoided: a stale device or a lost logout response revoking sessions created later. KEEP: every other behaviour, test and review patch.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | security | Re-registration replaces the password; verify now signs in, so a pre-hijacker keeps access | rejected | `RegistrationService._replace_unverified_user`. Vlad accepted the risk on 2026-11-05: asking for the password at verification adds friction, and the attack needs the victim to enter an unexpected second code. |
| 2 | security | Mass revocation misses a token inserted by a concurrent refresh | medium | READ COMMITTED snapshot. Patched: lock the user row first. |
| 3 | security | Logout with a revoked token skips reuse detection | medium | Patched in matrix. |
| 4 | security | Access token survives logout, unstated | low | Patched: stated, matrix row. |
| 5 | security, completeness | `verify_iat` uses the real clock; `sub` must be a string | medium | PyJWT api_jwt.py `_validate_iat`, `_validate_sub`. Patched Design Notes. |
| 6 | security, completeness | Short secret accepted outside tests | medium | `InsecureKeyLengthWarning` only warns. Patched: min 32. |
| 7 | security | Concurrent refreshes cause global logout | low | Patched: AD-19 frontend contract. |
| 8 | security | `delete_cookie` defaults to `path="/"` | medium | Starlette signature. Patched: clearing repeats attributes, tests. |
| 9 | security | Cross-site top-level POST clears cookies | low | Patched: clear only when a cookie arrived. |
| 10 | security | Lockout as DoS | low | Patched: lock never touches sessions, matrix row. |
| 11 | completeness | Cookies set on the injected Response are dropped on 401/204 | high | fastapi/routing.py:750. Patched: results, `SessionCookies` on the returned response. |
| 12 | completeness | Deploy AC says "branch deploys"; missing secret breaks the deploy | high | delivery.yml:105 runs on `main` only. Patched AC with Vlad's pre-merge step. |
| 13 | completeness | Counter state after lock undefined; 403 reset; `retry_after` | medium | Patched. |
| 14 | completeness | Registry path and `__init__` re-exports | low | Patched tasks. |
| 15 | completeness | CI value length vs conftest `setdefault` | low | Patched: 64-char hex, unconditional override. |
| 16 | verification-gap, blind | Row locks in refresh, logout and login untested; dropping `for_update` or `populate_existing` stays green | medium | Shared-connection harness cannot observe locks (same as registration row 15). Defer: two-connection fixture. |
| 17 | verification-gap | Token and lockout settings tested only at defaults | low | Deployed compose passes only the secret, so every environment runs the tested defaults. Defer. |
| 18 | blind | `refresh_tokens` grows without cleanup | medium | One row per refresh, nothing deletes. Defer with the `verification_codes` cleanup. |
| 19 | blind | `bad-signature` case also has `exp: 0`, so it passes without signature checks | low | `test_me_without_a_valid_session_returns_401`. Patch. |
| 20 | blind | `AccessTokenCodec.decode` branches (missing claims, non-int `exp`, other `alg`) untested | medium | Only four token shapes tested. Patch. |
| 21 | blind, edge | Argon2 runs while the user row is locked; parallel logins stall refresh | low | A locked account returns 423 before Argon2, so at most 5 hashes per lock window queue on the row. Rejected. |
| 22 | blind | Unknown email answers faster than a wrong password | low | Registration already reveals existence (409, 404); a dummy hash adds code for no gain. Rejected. |
| 23 | blind | No logs for reuse detection, lockout, revoked-token logout | medium | Nothing is logged. Defer to the logging stack (Phase 4). |
| 24 | blind, edge | `TOKEN_REFRESH_COOKIE_PATH` can diverge from the mounted router | low | Default matches the route; the setting is part of the frozen intent. Rejected. |
| 25 | blind | No ADR for the session model | low | workflow.md rule 5. Defer: one ADR after the auth stories, with the error-contract ADR. |
| 26 | blind | AD-19 silent on SSR with an expired access token | medium | Refresh is browser-only, so SSR after 15 idle minutes sees 401 with a live refresh cookie. Defer to the frontend auth work. |
| 27 | blind | No login test with a differently cased email | low | Normalisation is in `get_by_email`, untested for login. Patch. |
| 28 | edge | A token revoked by logout or mass revocation, presented again, triggers another mass revocation | medium | `SessionService.refresh`/`end` treat every revoked token as reuse, matching the frozen wording; a stale device or a lost logout response logs out sessions created later. Vlad chose to mark rotated tokens: only those trigger mass revocation. Patch (frozen block and matrix updated by Vlad's decision). |
| 29 | edge | Re-login with a live refresh cookie leaves the old token active | low | Fix adds a parameter to login for a rare leak. Rejected. |
| 30 | edge | Failed attempts never decay | low | Spec says consecutive failures; a decay window needs a new column nobody asked for. Rejected. |
| 31 | edge | Zero or negative TTL and limit settings accepted | low | Operator misconfiguration only (registration row 3). Rejected. |
| 32 | edge | `/health` and `GET /` not under `/api/v1` | false | Frozen decision: they stay at the root. |

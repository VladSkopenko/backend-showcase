---
title: 'Password reset by email code'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_commit: '4cc19ff7621a2c5e10874885cd13d90f34b4217b'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-registration-email-verification.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A user who forgot the password has no way back in. The Figma flow is three modals: "Reset Password" (email, Request Code), "Enter Verification Code" (code, "Resend in 59 seconds", Confirm) and "Reset Password" (new password and confirmation), ending on the sign-in modal with a "Your password was changed successfully" toast.

**Approach:** Three routes under `/api/v1/auth/password-reset`: `request` emails a 6-digit code, `verify-code` checks it without consuming it (the Confirm step), `confirm` checks it again, consumes it and sets the new password. Codes reuse `verification_codes` with a new purpose. Story 4 of 5 on `feature/auth-reset-oauth`.

## Boundaries & Constraints

**Always:**
- Decision (Vlad, 2026-11-09): `VerificationPurpose.PASSWORD_RESET` is added in migration `0004`, which also adds the index `ix_verification_codes_user_id_purpose_created_at` on `(user_id, purpose, created_at)` (explicit name in the model and the migration; the naming convention would name it after the first column only) and recreates the `user_id` foreign key with `ondelete="CASCADE"` (deferred-work item).
- Codes behave exactly like email verification codes: 6 digits, SHA-256 at rest, TTL, 5 wrong attempts invalidate a code, 60 s cooldown and 5 codes per hour, all from the existing `AuthSettings`. Limits are counted per purpose. Only the newest `PASSWORD_RESET` code of the user counts; an `EMAIL_VERIFICATION` code never resets a password.
- Decision (Vlad, spec review): reset codes also have a daily cap, `AuthSettings.max_reset_codes_per_day` (default 10), checked in `VerificationCodeService.issue` for `PASSWORD_RESET` only, with `retry_after` until the oldest code in the last 24 hours leaves the window (the later of all applicable limits, as today). It bounds guessing at 50 tries a day per account.
- Decision (Vlad): a repeated `request` is the resend; there is no separate resend route.
- Decision (Vlad): `request` for an unknown email returns 404 `USER_NOT_FOUND`, like `resend-code`. `verify-code` and `confirm` for an unknown email return the same 404.
- Decision (Vlad): `verify-code` checks the code without consuming it; a wrong code counts toward the 5 attempts. `confirm` takes `email`, `code`, `password`, `password_confirmation`, checks the code first and hashes the password only after the code passed, then consumes it. Wrong and expired codes are returned as results, not raised, so the attempt increment commits.
- Decision (Vlad): reset works for an unverified account and sets `email_verified_at`, because the code proves ownership of the address. It also works for a user without `password_hash` (Google-only accounts from story 5).
- A successful `confirm` replaces `password_hash`, sets `failed_login_attempts` to 0 and `login_locked_until` to null, and revokes every active refresh token of the user. It does not sign in (the design returns to the sign-in modal). Decision (Vlad, spec review): it never touches cookies; an access token issued before the reset stays valid until its `exp` (at most 15 minutes), as after logout.
- Password rules as in registration: 8 to 128 characters and a matching confirmation; the stricter rules shown in the design are the frontend's.
- `debug_code` in the `request` response only when `APP_ENVIRONMENT` is `local`.
- The email has the verification email's look: subject "Reset your password", a "Reset password" button to `{frontend_url}/reset-password?email=…&code=…` and the code in the letter-spaced block, plus a plain-text part. It is sent by a background task after the commit, and a send failure is logged without the code.
- All three routes lock the user row (`FOR UPDATE`) before touching codes.

**Never:** auto-login after reset, a reset token or a new table, changes to registration or login rules, IP rate limiting, cleanup of old codes (stays deferred), settings other than `max_reset_codes_per_day`, cookie changes on any reset route.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Request | existing user, verified or not | 202 `{}` (`debug_code` only in local); reset email sent | N/A |
| Request again too soon | last reset code < 60 s old, or 6th in an hour | 429 `RESEND_TOO_SOON` with `retry_after` | N/A |
| Daily cap | 11th reset code within 24 hours | 429 `RESEND_TOO_SOON`, `retry_after` until the oldest of those codes is 24 hours old | N/A |
| Request unknown | no such user | 404 `USER_NOT_FOUND`; no email | N/A |
| Verify code | correct, unexpired | 204; code not consumed; attempts unchanged | N/A |
| Verify wrong code | wrong code | 400 `CODE_INVALID`; attempts +1; after 5 wrong even the right code gets 400 | attempt commits |
| Expired | correct code after TTL, on verify-code or confirm | 400 `CODE_EXPIRED`; password unchanged | N/A |
| No reset code | none issued, or only an `EMAIL_VERIFICATION` code exists | 400 `CODE_INVALID` on verify-code and confirm | N/A |
| Confirm | correct code, valid passwords | 204; new password logs in, old one gets 401; code consumed (reuse → 400 `CODE_INVALID`); all refresh tokens revoked; no `Set-Cookie` | N/A |
| Access after reset | access cookie issued before confirm, within 15 min | `GET /me` 200 | N/A |
| Confirm, locked user | lockout active | 204; login with the new password succeeds at once | N/A |
| Confirm, unverified user | `email_verified_at` null | 204; `email_verified_at` set; login succeeds | N/A |
| Confirm, no password | `password_hash` null | 204; login with the new password succeeds | N/A |
| Confirm wrong code | wrong code | 400 `CODE_INVALID`; attempts +1; password unchanged | attempt commits |
| Bad input | passwords differ, < 8 or > 128 chars, code not 6 digits | 422 | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/core/auth/services/verification_code_service.py` -- `issue` (builds the only `IssuedCode`, line 50; `_ensure_issue_allowed` holds the cooldown and hourly logic to extend with the daily cap), `consume`; split the validity checks of `consume` into a shared private method and add `check` that runs them without setting `consumed_at`.
- `backend/src/app/features/core/auth/services/email_verification_service.py` -- pattern for a service that locks the user (`get_by_email(for_update=True)`) and returns code errors.
- `backend/src/app/features/core/auth/services/session_service.py` -- add `revoke_all(user=)` on top of `RefreshTokenRepository.revoke_all_active`.
- `backend/src/app/features/core/auth/services/verification_email_renderer.py`, `verification_email_service.py` (log text "Sending the verification email" becomes purpose-neutral), `endpoints/dependencies.py` (`get_verification_email_renderer`), `templates/verification_email.html` -- the renderer hardcodes subject, templates and `/verify-email`; key them by purpose. `IssuedCode` gains `purpose`.
- `backend/src/app/features/core/auth/endpoints/auth.py`, `errors.py` -- `verify_user_email` shows the result-to-`domain_error_response` pattern. No new error classes or statuses.
- `backend/src/app/features/core/auth/schemas/auth.py` -- `RegisterRequest` has the password rules and the match validator; `ResendCodeResponse` is the `{debug_code?}` shape.
- `backend/src/app/common/database.py:16` -- `ix` convention uses `column_0_label` only, hence the explicit index name.
- `backend/migrations/versions/0002_create_verification_codes.py` -- FK name `fk_verification_codes_user_id_users`, enum `verification_purpose`.
- `backend/tests/test_registration.py`, `test_login.py`, `conftest.py` -- fake email sender, `FakeClock`, `https://test` client, cookie assertions to reuse.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_password_reset.py` -- every matrix row through the HTTP API; time via the fake clock; the purpose-isolation and revoked-refresh rows assert the database state.
- [x] `backend/tests/test_verification_email.py` -- reset email: subject, code, `/reset-password` link in HTML and text; existing verification assertions keep passing with the new `render` signature.
- [x] `backend/tests/test_database.py` -- enum labels, the named index and `ON DELETE CASCADE` on the FK.
- [x] `backend/tests/test_settings.py` -- `AUTH_MAX_RESET_CODES_PER_DAY` mapping and default.
- [x] `backend/migrations/versions/0004_add_password_reset.py` -- `ALTER TYPE verification_purpose ADD VALUE 'PASSWORD_RESET'`; drop and recreate the FK with `ondelete="CASCADE"`; create the named index. Downgrade deletes `PASSWORD_RESET` rows, rebuilds the enum without the value, restores the FK and drops the index.
- [x] `backend/src/app/features/core/auth/enums/verification_purpose.py`, `models/verification_code.py` -- new member; `ForeignKey(..., ondelete="CASCADE")`; the named `Index` in `__table_args__`.
- [x] `backend/src/app/config/settings.py`, `backend/.env.example` -- `max_reset_codes_per_day: int = 10`.
- [x] `backend/src/app/features/core/auth/dto/issued_code.py`, `services/verification_code_service.py`, `session_service.py` -- `IssuedCode.purpose`; `check`; daily cap; `revoke_all`.
- [x] `backend/src/app/features/core/auth/services/password_reset_service.py` -- `PasswordResetService` with `request`, `verify_code`, `confirm`; returns `DomainError | None` for code results.
- [x] `backend/src/app/features/core/auth/services/verification_email_renderer.py`, `verification_email_service.py`, `templates/email_layout.html`, `verification_email.html`, `password_reset_email.html`, `password_reset_email.txt` -- purpose-keyed rendering; both HTML templates extend the shared layout so the look stays identical.
- [x] `backend/src/app/features/core/auth/schemas/auth.py`, `schemas/__init__.py` -- `PasswordResetRequest`, `PasswordResetCodeRequest`, `PasswordResetConfirmRequest` (own match validator; `RegisterRequest` untouched).
- [x] `backend/src/app/features/core/auth/endpoints/auth.py`, `dependencies.py` -- three routes, the service provider, the renderer provider without the hardcoded purpose.

**Acceptance Criteria:**
- Given the local stack with `APP_ENVIRONMENT=local`, when request → verify-code → confirm run through curl with the `debug_code`, then login works with the new password and the old refresh cookie gets 401.
- Given the merge to `main` and the dev deploy, when Vlad requests a reset for his account, then the reset email arrives in the verification email's style.
- Given CI, then lint, mypy, import-linter, the migration round-trip with `alembic check`, and tests pass.

## Implementation Notes

- `confirm` runs `check`, then Argon2, then `consume` (which re-validates under the same row lock), so a wrong code never pays for a hash and the code is consumed only after the hash succeeded.
- `email_verified_at` is set by `confirm` only when it is null; a verified user keeps the original time.
- `request` reuses `ResendCodeResponse` (`{debug_code?}`); no new response schema.
- The renderer keys subject, template name and frontend path by `VerificationPurpose` (class-attribute dicts); the context key `confirm_url` became `action_url`. The shared `email_layout.html` takes the subject as its `<title>` and `<h1>`; each email fills `intro`, `button_label`, `code_hint` and `footer` blocks.
- The send-failure log reads "Sending the <PURPOSE> email to <address> failed", still without the code.
- Migration 0004 compares `purpose::text` in the downgrade `DELETE`, so it never touches the enum value as a literal. The downgrade path with existing `PASSWORD_RESET` rows was not exercised (no data was written to the throwaway database by SQL).
- Verification: full command list green (134 tests); round-trip `upgrade head` → `downgrade 0003` → `upgrade head` → `alembic check` clean on a throwaway `postgres:18` on port 5439; live curl check (register → verify-email → reset request → wrong and right verify-code → confirm without `Set-Cookie` → reuse 400 → old refresh cookie 401 → old password 401 → new password 200) ran against the same throwaway database with environment variables set in the process. The working database `app` was not migrated, so the local live check from the acceptance criteria is still open.

## Spec Change Log

- 2026-11-09, spec review: Vlad added a daily cap on reset codes (`max_reset_codes_per_day`, default 10) and removed cookie clearing from `confirm`; the matrix gained the daily cap, expired confirm, no-reset-code and access-after-reset rows; the index got an explicit name. Known-bad states avoided: about 20% a year to guess a verified account's code at 25 tries an hour; clearing another signed-in user's cookies without revoking their token; an index name that `alembic check` reports as drop-and-add.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | 25 guesses an hour (600 a day) against a verified account | high | `AuthSettings` defaults; Vlad chose a daily cap. Patched. |
| 2 | spec review | Composite index named by the convention after its first column only | medium | `database.py:16`. Patched: explicit name. |
| 3 | spec review | Access token survives the reset, unstated | medium | `CurrentUserService.get` decodes only. Patched: stated, matrix row. |
| 4 | spec review | Expired confirm, no reset code, cookies on failure, hash order undefined | medium | Patched: matrix rows; code before Argon2; cookies never touched. |
| 5 | spec review | Confirm clears another signed-in user's cookies without revoking their token | low | `SessionCookies.clear` checks presence only. Vlad: no cookie changes. Patched. |
| 6 | spec review | Renderer and `IssuedCode` call sites missing from tasks | low | Patched tasks and Code Map. |
| 7 | spec review | Alembic detection claims unverified | low | Verified, see Design Notes. Patched. |
| 8 | verification-gap | Daily cap limited to `PASSWORD_RESET` untested; dropping the purpose guard stays green | medium | Registration tests issue at most 5 codes a day; a frequent resender would hit 429. Patched: `test_the_daily_reset_cap_does_not_limit_verification_codes`. |
| 9 | verification-gap, blind | Downgrade of 0004 never run with `PASSWORD_RESET` rows present | medium | CI round-trip and the throwaway run used empty tables. Defer: seeded migration tests are a repo-wide decision, with the AD-9 rollback item. |
| 10 | verification-gap, edge, blind | `AppSettings.backend_url` / `APP_BACKEND_URL` outside the spec | false | Vlad added it himself on this branch (2026-11-09) for later use; not part of the implementation. |
| 11 | edge, blind | `max_reset_codes_per_day` 0 or negative raises `IndexError` (500) | low | `today[-0]` on an empty list. Operator misconfiguration only, settled in registration row 3 and login row 31. Rejected. |
| 12 | blind | Three purpose dicts in the renderer can drift for a future purpose | low | Both members present in all three; no purpose is planned. Rejected. |
| 13 | blind | Reset email send failure not tested | low | Same `VerificationEmailService.send` path as the tested verification failure; only the purpose name in the message differs. Rejected. |
| 14 | blind | Purpose isolation tested one way; reset limits vs verification limits one way | low | Both directions rely on the purpose filter in `get_latest` and `list_creation_times_since`, which the existing isolation tests break if removed. Rejected. |
| 15 | blind | Cascade checked as metadata only | false | The test reflects the FK from the migrated database; deleting rows is PostgreSQL's job. Round-trip psql showed `confdeltype = c`. |
| 16 | blind | Layout test weak; text parts duplicate structure | low | Cosmetic test and template duplication; both emails render from the shared HTML layout. Rejected. |
| 17 | blind | Argon2 under the user-row lock in `confirm` | low | Hash runs only after a correct code, once per code; same reasoning as login row 21. Rejected. |
| 18 | blind | Reset decisions not in an ADR | low | workflow.md rule 5. Defer: joins the auth ADR batch already in deferred-work. |

## Design Notes

- PostgreSQL 18 docs (`sql-altertype.html`, Notes): `ADD VALUE` may run inside a transaction block, but the new value "cannot be used until after the transaction has been committed"; there is no `DROP VALUE`. So 0004 adds the value and never uses it, and downgrade rebuilds the type: rename the old one, create the new one, `ALTER COLUMN ... TYPE ... USING purpose::text::verification_purpose`, drop the old type.
- Alembic autogenerate (docs: "What does Autogenerate Detect"; alembic 1.20.1 `ddl/impl.py` `compare_type`, `ddl/_autogen.py` FK signature): enum members are not compared, a changed `ondelete` and an added `Index` are. The model must carry the FK `ondelete` and the named index, or `alembic check` fails after 0004.
- The daily cap query uses the new index; it reads `created_at` for the user and purpose within 24 hours, like the hourly one.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass (tests build `app_test` themselves).
- On a throwaway `postgres:18` container, never on `app`: `alembic upgrade head`, `downgrade 0003`, `upgrade head`, `alembic check` -- clean. The working database `app` is migrated only with Vlad's permission, before the local live check.

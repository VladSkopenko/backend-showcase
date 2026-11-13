# Deferred work

- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Add a test that the module-level `app.main:app` serves `/health`.
  evidence: Renaming the module attribute keeps the suite green but breaks `uvicorn app.main:app`; the DevOps phase healthcheck will cover it end to end.
- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Complete the ADR 11 import rules for `config`, core-to-core imports and the callers of `application_services`.
  evidence: The current wording does not list `config`, makes "features never import each other" clash with "may import core features", and does not say who calls `application_services`.
- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Bring `naming_convention` and "background tasks open their own session" from ADR 11 into `.claude/rules/backend.md`.
  evidence: Agents load `backend.md`, not the ADR, so the first model or background task can miss these rules.
- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Decide `expire_on_commit=False` or build response schemas before the session dependency exits.
  evidence: Unverified (medium if true): it depends on whether response serialization runs after the `scope="function"` commit; settle when the session dependency is written.
- source_spec: `_bmad_output/implementation-artifacts/spec-database-foundation.md`
  summary: Implement the AD-9 rollback from ADR 5 in `deploy/app/deploy.sh`: record `alembic current`, and when the health gate fails run `alembic downgrade <recorded revision>` with the new image, then start the previous digest.
  evidence: Deferred by the spec's Never list. Today a deploy whose new API fails `up --wait` leaves the new schema and the failing container in place.
- source_spec: `_bmad_output/implementation-artifacts/spec-database-foundation.md`
  summary: Type-check `backend/migrations` (`mypy src tests migrations`) in CI and CLAUDE.md, and use `docker compose up -d --wait` in the CLAUDE.md local database command.
  evidence: `env.py` and revisions are never checked under `strict = true`; both fixes edit CLAUDE.md, an agent-context file.
- source_spec: `_bmad_output/implementation-artifacts/spec-database-foundation.md`
  summary: Fix the Alembic revision naming convention (`--rev-id` sequence or a date prefix in `file_template`) before the second migration.
  evidence: 0001 was named by hand; the next autogenerate produces a hex id, and files stop sorting in order.
- source_spec: `_bmad_output/implementation-artifacts/spec-database-foundation.md`
  summary: Write a runbook for rotating `POSTGRES_PASSWORD` per environment (`ALTER ROLE app PASSWORD ...` before updating the GitHub secret).
  evidence: The secret only applies to an empty data directory; changing it alone breaks the API's connection.
- source_spec: `_bmad_output/implementation-artifacts/spec-registration-email-verification.md`
  summary: Index `verification_codes (user_id, purpose, created_at)`, add `ondelete="CASCADE"` to its user FK, and clean up old codes.
  evidence: No consumer deletes users yet and the table is small; needed before account deletion or real traffic.
- source_spec: `_bmad_output/implementation-artifacts/spec-registration-email-verification.md`
  summary: Test the user-row lock in verify, resend and register with two concurrent connections.
  evidence: The shared-connection test harness cannot observe locks, so dropping `for_update=True` passes every test.
- source_spec: `_bmad_output/implementation-artifacts/spec-registration-email-verification.md`
  summary: Write an ADR for the error contract (DomainError, per-feature status maps, result-instead-of-raise), the OOP/feature folder layout and the unmerged-migration rule.
  evidence: workflow.md rule 5; these decisions now live only in backend.md and the spec.
- source_spec: `_bmad_output/implementation-artifacts/spec-registration-email-verification.md`
  summary: Make 422 validation errors use the `{"code","message"}` shape and document error responses in OpenAPI.
  evidence: The frontend currently parses two error shapes, and `/docs` shows only success models.
- source_spec: `_bmad_output/implementation-artifacts/spec-registration-email-verification.md`
  summary: Mask email addresses in logs.
  evidence: Failed sends log the full recipient; matters once logs ship to VictoriaLogs (Phase 4).
- source_spec: `_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md`
  summary: Test the row locks in refresh, logout and login with two concurrent connections (two refreshes of one token, reuse versus rotation, parallel wrong passwords).
  evidence: The shared-connection harness cannot observe locks, so dropping `for_update` or `populate_existing` in `SessionService._lock_token`, `RefreshTokenRepository.get_by_hash` or `LoginService.log_in` passes every test.
- source_spec: `_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md`
  summary: Test non-default `TOKEN_*` and `AUTH_*` login values end to end (cookie Max-Age and Path, JWT exp, lockout threshold).
  evidence: Every assertion holds whether the code reads the setting or a literal; deployed environments run the defaults today.
- source_spec: `_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md`
  summary: Delete expired `refresh_tokens` rows, together with the old `verification_codes` cleanup.
  evidence: Every refresh inserts a row and nothing deletes them; revoked rows matter for reuse detection only until `expires_at`.
- source_spec: `_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md`
  summary: Log security events: refresh reuse with mass revocation, lockout, logout with a revoked token (user id only, no tokens).
  evidence: None of them writes a log line; they are the first alerts worth having once logs ship (Phase 4).
- source_spec: `_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md`
  summary: Write an ADR for the session model (rotation without a grace window, non-revocable 15-minute access JWT, HS256 secret, `/api/v1` prefix), with the error-contract ADR after the auth stories.
  evidence: workflow.md rule 5; AD-19 records only the frontend contract, not the reasons or rejected options.
- source_spec: `_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md`
  summary: Settle in AD-19 what the frontend's server-side rendering does on 401 with a live refresh cookie (neutral shell and client check, or redirect).
  evidence: Refresh is browser-only, so SSR after 15 idle minutes gets 401 from `/me` while the session is still alive.
- source_spec: `_bmad_output/implementation-artifacts/spec-health-database-check.md`
  summary: Record in an ADR (with the auth ADR batch) that `/health` now depends on the database, and what that means for the deploy gate, the ADR 5 rollback and alerting.
  evidence: workflow.md rule 5; ADR 5 and AD-9 rely on `/health` without saying it checks PostgreSQL.
- source_spec: `_bmad_output/implementation-artifacts/spec-health-database-check.md`
  summary: Log a failed `/health` database probe with the exception type only (refused, timeout, credentials).
  evidence: A 503 from the Docker healthcheck or the deploy gate cannot be told apart today; belongs with the Phase 4 logging items.
- source_spec: `_bmad_output/implementation-artifacts/spec-separate-test-database.md`
  summary: Test the conftest guard that stops the session when settings were cached with a database other than `app_test` (pytester subprocess).
  evidence: Removing or inverting the guard passes every test; it was verified manually only.
- source_spec: `_bmad_output/implementation-artifacts/spec-separate-test-database.md`
  summary: Add to `.claude/rules/workflow.md` that review subagents never run pytest; only the main agent runs the suite.
  evidence: Parallel runs drop each other's `app_test`; review prompts in this session needed an explicit "do not run pytest".
- source_spec: `_bmad_output/implementation-artifacts/spec-separate-test-database.md`
  summary: Record the test database contract (`app_test` recreated per run, one run per server, CI round-trip on `app`) in the ADR batch.
  evidence: workflow.md rule 5.
- source_spec: `_bmad_output/implementation-artifacts/spec-password-reset.md`
  summary: Test the 0004 downgrade with `PASSWORD_RESET` and `EMAIL_VERIFICATION` rows present (reset rows deleted, verification rows survive the enum rebuild).
  evidence: CI round-trip and the throwaway verification ran on empty tables; dropping the DELETE would only fail on a database that has issued reset codes. Belongs with the AD-9 rollback item.
- source_spec: `_bmad_output/implementation-artifacts/spec-password-reset.md`
  summary: Add the password reset decisions to the auth ADR batch (access token survives a reset, reset verifies the email, daily cap for reset codes only, check-then-confirm without a reset token).
  evidence: workflow.md rule 5; they live only in the spec.
- source_spec: `_bmad_output/implementation-artifacts/spec-google-oauth.md`
  summary: Test that the real `get_oauth_clients` wiring registers Google from the same settings the provider registry reads.
  evidence: Every app test overrides the dependency; a drift would answer `OAUTH_FAILED` on every real sign-in with all tests green. The dev live sign-in covers it today.
- source_spec: `_bmad_output/implementation-artifacts/spec-google-oauth.md`
  summary: Check Google's guidance on trusting `email_verified` for non-Gmail addresses (the `hd` claim) before linking a Google account to an existing password account.
  evidence: Unverified (medium if true): a third-party address that changed owners could link to an existing account; the review cited the guidance from memory.
- source_spec: `_bmad_output/implementation-artifacts/spec-google-oauth.md`
  summary: Add the Google sign-in decisions to the auth ADR batch (email linking only when verified, password wipe on unverified accounts, one link per provider, OAuth through the frontend proxy).
  evidence: workflow.md rule 5.
- source_spec: `_bmad_output/implementation-artifacts/spec-menu-dishes.md`
  summary: Decide caching for dish pictures: `Cache-Control` on upload and content-hashed keys, together with whether anonymous GETs count toward the 50,000 Always Free requests.
  evidence: Same key on every seed run and no cache headers; replaced pictures stay stale in caches, and each view may hit the bucket.
- source_spec: `_bmad_output/implementation-artifacts/spec-locations.md`
  summary: Document the local picture seeds (`app.scripts.seed_menu`, `app.scripts.seed_location_photos`) and the per-environment bucket upload in README or CLAUDE.md Commands.
  evidence: Both commands live only in specs; every environment bucket needs the pictures before `image_url`s work.
- source_spec: `_bmad_output/implementation-artifacts/spec-book-a-table.md`, `_bmad_output/implementation-artifacts/spec-edit-booking.md`
  summary: Test the user and table row locks in booking create, and the user, table and booking row locks with `populate_existing` in booking edit, with two concurrent connections, as for the auth user-row lock.
  evidence: The shared-connection test harness cannot observe locks or a stale identity-map object, so dropping any `for_update=True` or `populate_existing` passes every test.
- source_spec: `_bmad_output/implementation-artifacts/spec-book-a-table.md`
  summary: Test the `IntegrityError` on `ex_bookings_table_id_period` turning into `SLOT_UNAVAILABLE` in `BookingService.create`.
  evidence: On one connection the locked overlap check catches every table overlap first, so the branch is unreachable; it needs two connections racing past the check.
- source_spec: `_bmad_output/implementation-artifacts/spec-edit-booking.md`
  summary: Test the `IntegrityError` on `ex_bookings_table_id_period` turning into `SLOT_UNAVAILABLE` on the flush in `BookingService.edit`.
  evidence: Same as for create: one shared connection never gets past the locked overlap check with a conflicting row.

## Deferred from: code review of spec-locations.md (2026-11-10)

- Change the `uq` naming convention to `uq_%(table_name)s_%(column_0_N_name)s` so composite unique constraints get full names without explicit `name=`; existing single-column names stay the same.
- Move the per-feature `SessionDep` and `SettingsDep` aliases (auth, menu, locations, health) to one shared place.
- source_spec: `_bmad_output/implementation-artifacts/spec-n8n-booking-simulator.md`
  summary: Test the dev branch of migration `0011` (four verified bots with the exact hash, downgrade removing them with their bookings, a taken email failing the upgrade) in CI.
  evidence: The only test checks that `app_test`, migrated as `local`, has no bots; a typo in the environment guard or a dropped column passes it. Needs a second throwaway database and a `dev` settings override inside pytest; checked once by hand on a throwaway `postgres:18`.
- source_spec: `_bmad_output/implementation-artifacts/spec-n8n-booking-simulator.md`
  summary: End the bots' sessions: the simulator logs in on every run and never calls `/auth/logout`, so dev gains one `refresh_tokens` row per run (about 288 a day) with no cleanup.
  evidence: `SessionService` inserts a `RefreshToken` on every login; nothing deletes expired rows. A logout must run on every branch, including the ones that stop early.
- source_spec: `_bmad_output/implementation-artifacts/spec-booking-invites.md`
  summary: Test the join locks (the joiner's user row, then the booking row with `populate_existing`, two joins racing for the last seat, a join racing an edit that lowers `party_size`) and the first-link race (two first `GET /bookings/{id}/invite` requests answering the same code) with two concurrent connections.
  evidence: The shared-connection test harness cannot observe locks or a stale identity-map object, so dropping `for_update=True` in `ParticipantService.join` or `lock_owned` passes every test.
- source_spec: `_bmad_output/implementation-artifacts/spec-preorder-cart.md`
  summary: Test that the booking row lock in `ParticipantService.lock_participant` serialises pre-order writes with two concurrent connections: a double submit (the second answers `CART_EMPTY`), two PUTs of one dish (one line, no unique-index 500), and a write racing the owner's cancel.
  evidence: The shared-connection test harness cannot observe locks or a stale identity-map object, so dropping `for_update=True` or `populate_existing` in `BookingRepository.get_participation` passes every test. The booking lock alone serialises the double submit and the write racing a cancel; the partial index `ix_preorder_items_participant_id_dish_id_draft` backstops only two concurrent PUTs of one dish.
- source_spec: `_bmad_output/implementation-artifacts/spec-preorder-cart.md`
  summary: Expose whether pre-order is open (for example `preorder_open` or `preorder_closes_at`) in the booking object, so the cart and the "Create New Pre-Order" button can be disabled before a 409 `PREORDER_CLOSED`.
  evidence: Figma has a disabled and an enabled "Create New Pre-Order" variant; `ParticipantAccess.preorder_open` is already computed in core. The lock window and pre-order statuses are planned for PR 4.

## Deferred from: code review of 1-large-party-booking-requests (2026-11-13)

- source_spec: `_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/1-large-party-booking-requests.md`
  summary: No pytest exercises migration downgrades; 0016's downgrade (PENDING to CANCELLED, rebuilt default and exclusion constraint) is covered only by CI's empty round trip and a manual check.
  evidence: grep finds no downgrade in backend/tests; conftest upgrades app_test once per session, so a downgrade test needs its own database harness.

## Deferred from: review of 2-staff-role-and-request-decisions (2026-11-13)

- source_spec: `_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/2-staff-role-and-request-decisions.md`
  summary: No pytest exercises the 0017 downgrade with a REJECTED row; covered only by CI's empty round trip and a manual check.
  evidence: same missing downgrade-with-data harness as for 0016.
- source_spec: `_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/2-staff-role-and-request-decisions.md`
  summary: Requests rejected because a competitor was approved carry the approver's decided_by_id and the approval time, indistinguishable from a deliberate rejection; the story 9 staff dashboard must tell them apart (or a decision reason column is added then).
  evidence: reject_pending_overlapping stamps the same decided_at and decided_by_id as the approval.

## Deferred from: review of 3-request-decision-notifications (2026-11-13)

- source_spec: `_bmad_output/implementation-artifacts/spec-restaurant-simulation/stories/3-request-decision-notifications.md`
  summary: Two narrow deadlock windows remain after recipients are locked first: a user who joins a competing request between the unlocked read and the user lock, and the staff user's row key-shared through decided_by_id after the table lock.
  evidence: both need a concurrent join or a staff member booking the same table during their own decision; Postgres aborts one transaction with a deadlock error (500).

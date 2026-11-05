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

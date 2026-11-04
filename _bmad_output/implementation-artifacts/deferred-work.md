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
- source_spec: `_bmad_output/implementation-artifacts/spec-import-linter-contracts.md`
  summary: Decide where domain exceptions live and where the handler that maps them to HTTP responses is registered.
  evidence: ADR 11 says services raise domain exceptions and the API layer translates them, but not where either lives; the first real feature would choose on its own.
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
- source_spec: `_bmad_output/implementation-artifacts/spec-database-foundation.md`
  summary: Normalise email to lowercase where users are written (OAuth PR), or add a unique index on `lower(email)`.
  evidence: `uq_users_email` is case-sensitive, so `Ada@x.com` and `ada@x.com` would create two users on OAuth sign-in.

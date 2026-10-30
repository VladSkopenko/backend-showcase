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

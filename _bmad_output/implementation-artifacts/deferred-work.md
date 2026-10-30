# Deferred work

- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Settings are read at import through a cached get_settings(), so tests can override them only via cache_clear().
  evidence: app.main builds the app at import; resolve when database settings arrive (factory without module-level settings read, or Depends(get_settings)).
- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: No test covers the module-level `app` that uvicorn serves.
  evidence: renaming it keeps tests green; the DevOps-phase container healthcheck will exercise app.main:app.
- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Clarify ADR 11 and backend.md import rules for config, core-to-core imports and callers of application_services.
  evidence: current wording says features import only core and common, which omits config and leaves core-to-core and application_services callers undefined.
- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Carry the ADR 11 naming_convention and background-task session rules into backend.md.
  evidence: agents load backend.md, not the ADR, when editing backend/**.
- source_spec: `_bmad_output/implementation-artifacts/spec-backend-skeleton-health.md`
  summary: Decide expire_on_commit=False or build response schemas before the session dependency commits.
  evidence: unverified; with async SQLAlchemy, lazy-loading expired attributes after commit raises MissingGreenlet; settle in the database spec.

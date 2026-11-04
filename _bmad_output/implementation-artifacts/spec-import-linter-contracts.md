---
title: 'Enforce ADR 11 import rules with import-linter'
type: 'chore'
created: '2026-11-01'
status: 'done'
route: 'oneshot'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** ADR 11's import rules are a convention only. A pull request can break them without anyone noticing until review.

**Approach:**
- Add import-linter as a dev dependency of `backend/`.
- Encode the ADR 11 dependency rules as contracts in `backend/pyproject.toml`: feature layers, endpoints never reach repositories or models, only endpoints import schemas, no `fastapi` or `starlette` below endpoints, regular features independent, `common` and core never import regular features, and `application_services` callers.
- Use wildcards so new features are covered without edits where import-linter allows it.
- Prove each contract catches a violation.
- CI runs `uv run lint-imports`; Vlad owns that step.

</frozen-after-approval>

## Implementation Notes

- import-linter 2.15 added via `uv add --dev`. Its 7 contracts are in `backend/pyproject.toml` under `[tool.importlinter]`.
- On the current code, `uv run lint-imports` reports 7 kept. pytest, ruff and mypy still pass, and `uv lock --check` passes.
- Each contract was proven against a deliberate violation in a scratch copy. Contracts 1–7 were run by a research subagent; contracts 4, 6 and 7 were re-run after the final edit. None of these violations touched the repo.
- Decision: core features never call `application_services`. Contract 6 forbids `app.features.core` from importing `app.features.*`, which includes `application_services`, so contract 7 allows only regular endpoints and background tasks. ADR 11 and `.claude/rules/backend.md` now say the same.
- `app.common`, `app.features.application_services` and `app.infrastructure.background_tasks` do not exist yet, so the contracts use the `.**` form for them. A plain module name that does not exist is a hard error. `.**` skips the package's own `__init__`, so the comment in pyproject says to drop `.**` once each package exists.
- Not encoded: "core features import each other one way only". It stays a convention, recorded in ADR 11.
- `.import_linter_cache/` added to `.gitignore`.
- No automated test was written: this is configuration, and the proof is the violation runs above.

## Review Triage Log

| # | Finding (Blind Hunter) | Verdict | Action |
|---|---|---|---|
| 1 | The forbidden contract on endpoints also flags the allowed indirect chain `endpoints -> services -> models` | high | patched: `allow_indirect_imports = "true"`, confirmed in a scratch copy (legal chain kept, direct import broken) |
| 2 | The rules said every new feature must be added to the contracts, but wildcards already cover new features; the real manual step (dropping `.**`) was only in a pyproject comment | medium | patched in ADR 11 and `backend.md` |
| 3 | `app.features.*` includes core, so `common` may not import core features, which the ADR did not say | medium | patched: the ADR now says `common` imports no features; the contract is renamed and commented |
| 4 | `application_services` and background tasks were not covered by the HTTP-free rule | medium | patched: added to the HTTP contract and the ADR |
| 5 | A typo in a wildcard pattern passes silently | low | rejected: the fix adds a fixture package or meta-test; patterns were checked against violations |
| 6 | ADR 11 was edited in place with no amendment note | low | patched: Status line records the 2026-11-01 amendment |
| 7 | CLAUDE.md commands miss `lint-imports`; the `.claude/settings.json` allowlist lacks it | medium | CLAUDE.md patched; the allowlist is left for Vlad, since settings.json holds the guardrails |
| 8 | Where domain exceptions and their HTTP translation live is unspecified | medium | deferred |
| 9 | CI does not run on push to `rc`/`prod` | low | rejected: those branches only change through PRs, which run CI; ci.yml is Vlad's |
| 10 | The first failing CI step hides the later ones | low | rejected: optional `if: ${{ !cancelled() }}` mentioned to Vlad; ci.yml is his |
| 11 | Actions are pinned by tag, not SHA; trailing whitespace in ci.yml | low | rejected: already discussed, Vlad's choice |
| 12 | `app.config` has no contract against importing features | low | rejected: config holds only settings; a contract for it guards a path not seen |

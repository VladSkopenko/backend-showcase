# Workflow

1. Spec first. Specs and stories come from the BMAD skills and land in
   `_bmad_output/implementation-artifacts/`. Fixes found in review or live runs get a spec too.
   Never reverse-engineer a spec format from old files.
2. Tests first. Write failing tests before the implementation. Task lists order test files before
   the files they cover.
3. Implement exactly the spec. No extra fields, parameters, optimizations or safety hedges that
   nobody asked for: raise them at the spec stage or leave them out.
4. Review with the code-review skills, then verify live through the real API.
5. Record non-obvious decisions as ADRs in `docs/adr/`.

## Planning
- No time estimates in specs.
- Prefer phased pull requests over a big-bang change. Inline non-obvious gotchas in the spec.
- Write specs directly: no deep code dives and no deployment details during the spec step.

## Review findings
- Before reporting a missing producer or required field, check the real call sites. `git diff HEAD`
  includes uncommitted local changes, so "not in HEAD" does not mean "foreign".
- Before adding or removing a guard on a status, find every consumer of that status.
- Fix wrong data where it is written. Never patch it with per-request queries or parsers; if the fix
  is out of scope, propose a separate task.

## Infrastructure is Vlad's
CI/CD, git hooks, Dockerfiles, compose files, Prometheus, Grafana, the logging stack, n8n and
Terraform are built by Vlad. Explain, review and point to documentation; write these files only when
he asks.

## Tooling
- Keep the allowlist in `.claude/settings.json` current so read-only tools and review agents run
  without prompts.

---
title: 'Group the API docs by user flow'
type: 'chore'
created: '2026-11-09'
status: 'done'
baseline_commit: '756dfc96399b7ec47a2d69217eb058272f908b65'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Swagger at `/docs` lists all fourteen auth routes under one `auth` tag, so a reader cannot tell which routes belong to registration, password reset, the session or Google sign-in, and `provider_slug` is a free text field.

**Approach:** Decision (Vlad, 2026-11-09): tag every route by user flow — Registration (register, verify-email, resend-code), Password reset (request, verify-code, confirm), Session (login, refresh, logout, me), OAuth sign-in (provider login and callback), Health (`/`, `/health`) — with a description per tag, shown in that order, and a short description per route; the OAuth routes say they are browser navigations answering with redirects, never `fetch` calls. `provider_slug` documents its allowed values (`google`) without changing validation, so an unknown slug still answers 404. Paths, status codes and behaviour stay the same. The rule goes into `.claude/rules/backend.md` as a project convention. Error responses in OpenAPI stay deferred.

</frozen-after-approval>

## Implementation Notes

- Tag names and descriptions live in `AuthOpenApiTags` and `HealthOpenApiTags` (`endpoints/openapi_tags.py` per feature); `create_app` passes them to `openapi_tags`, auth first.
- Route descriptions name limits without numbers, because the numbers come from `AuthSettings` and may differ per environment.
- OAuth routes declare `response_class=RedirectResponse`, so their 302 carries no JSON body in the schema.
- `provider_slug` gets `json_schema_extra={"enum": [...]}` built from `OAuthProvider` slugs; validation is unchanged, an unknown slug is still 404 (`test_unknown_provider_is_404`).
- New `backend/tests/test_openapi.py`, written first (17 of 18 failed before the change). Convention added to `.claude/rules/backend.md` under "API docs".
- Verification: ruff, format check, mypy, lint-imports, 209 tests pass.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | blind | Intent says fourteen auth routes; there are twelve plus two health routes | low | Frozen intent wording; behaviour unaffected. Rejected. |
| 2 | blind | Limits hard-coded as numbers in descriptions drift from `AuthSettings` | medium | `settings.py` values are overridable per environment. Patched: limits named without numbers; rule added. |
| 3 | blind | `verify-email` and code expiry not described | low | Patched with #2. |
| 4 | blind | `confirm` does not say it verifies the email | low | `PasswordResetService.confirm` sets `email_verified_at`. Patched. |
| 5 | blind | OAuth 302 documented as a JSON response | low | FastAPI default `JSONResponse`. Patched: `response_class=RedirectResponse`. |
| 6 | blind | Rule lists today's tags and will go stale | low | Patched: "for example". |
| 7 | blind | Two comments on one decision in `get_oauth_provider` | low | Patched: one comment. |
| 8 | blind | Spec lacks acceptance and verification sections | false | Oneshot route keeps only Intent and Implementation Notes by design. |
| 9 | blind | OAuth test matches the substring "fetch" only | low | Patched: also asserts "never". |

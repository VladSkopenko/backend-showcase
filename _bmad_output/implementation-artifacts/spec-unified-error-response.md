---
title: 'One error response format for the whole API'
type: 'feature'
created: '2026-11-11'
status: 'done'
baseline_commit: '945427ac5b18f785ee3b47d88cb5450b21efe312'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0012-unified-error-response.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Domain errors reach the client as `{code, message}`, but validation errors keep FastAPI's `{"detail": [...]}` (raw pydantic text, echoed input, no usable field), unknown routes and methods return `{"detail": ...}`, unhandled exceptions return plain text, an unmapped domain error leaks its message as a 500, `ACCOUNT_LOCKED` has no `retry_after`, and no error is documented in OpenAPI.

**Approach:** Implement ADR 12: one body `{code, message, retry_after?, details?}` built in one place, app-level handlers for validation, HTTP-layer and unhandled errors, `retry_after` on `ACCOUNT_LOCKED`, and per-route error documentation from a shared `ErrorResponse` schema. The frontend (`~/Desktop/family-rest`) must keep working with no change.

## Boundaries & Constraints

**Always:** every JSON error body comes from one builder in `app/common`; `message` is project-written English; headers on HTTP-layer errors (e.g. `Allow`) are kept; a 500 is always `{"code": "SERVER_ERROR", "message": "Something went wrong."}`; existing domain codes, messages and statuses stay unchanged except `ACCOUNT_LOCKED` gaining `retry_after`.

**Never:** change `/` and `/health` bodies (including 503) or the OAuth `?auth_error=` redirects; return pydantic `msg`, `input`, `ctx` or `loc` as-is; rewrite FastAPI's OpenAPI generation; touch the frontend repository.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Query out of range | `GET /api/v1/menu/dishes?limit=100` | 422 `VALIDATION_ERROR`, `message: "Must be at most 50."`, `details: [{"field": "limit", "message": "Must be at most 50."}]` | no `input`; top-level `message` is always the first detail's message (decided: the sign-up form shows only `message`) |
| Body field invalid | register with `email: "x"` | 422, `details` has `field: "email"`, `message: "Enter a valid email address."` | — |
| Passwords differ | register/reset-confirm with mismatch | 422, `details: [{"field": "password_confirmation", "message": "Passwords do not match."}]` | — |
| Missing field | body without `code` | `{"field": "code", "message": "This field is required."}` | — |
| Malformed JSON | body `{bad` | 422, one detail with no `field`, `message: "Request body is not valid JSON."` | handled before reading `loc` (`loc` holds a char offset) |
| Empty body | POST with no body | 422, one detail with no `field`, `message: "Request body is required."` | — |
| Body not an object | JSON array or `text/plain` | 422, one detail with no `field`, `message: "Request body must be a JSON object."` | — |
| Bad path UUID | `GET /api/v1/menu/dishes/abc` | 422, `field: "dish_id"` | — |
| Unknown route | `GET /nope` | 404 `NOT_FOUND`, `message: "Not found."` | — |
| Wrong method | `DELETE /api/v1/menu/dishes` | 405 `METHOD_NOT_ALLOWED`, `message: "Method not allowed."`, `Allow` header kept | — |
| Unknown OAuth provider | `GET /api/v1/auth/yahoo/login` | 404 `NOT_FOUND` (raised by `get_oauth_provider`, not the router) | — |
| Password too short, same confirmation | `password` and confirmation both `"short"` | only the `password` detail, no mismatch detail | — |
| Unhandled exception | any route raises | 500 `SERVER_ERROR` generic body | traceback logged once |
| Unmapped DomainError | raised with no status in the map | 500 `SERVER_ERROR` generic body | logged with traceback |
| Account locked | login while locked | 423 `ACCOUNT_LOCKED`, `retry_after` = seconds left (rounded up), `Retry-After` header, message text unchanged | — |

</frozen-after-approval>

## Code Map

- `src/app/common/errors.py` -- `DomainError(code, message)`, instance `retry_after`. Add a class-level `code` so docs can list codes without instances.
- `src/app/common/error_responses.py` -- `domain_error_response(error, statuses)`; becomes the single body builder plus the OpenAPI helper and `ErrorResponse` model.
- `src/app/main.py:52` -- only `DomainError` handler today; merged `ERROR_STATUSES` here.
- `src/app/features/core/*/services/exceptions.py` -- every DomainError subclass (auth 16, menu 2, locations 2).
- `src/app/features/core/*/endpoints/errors.py` -- per-feature status maps; OAuth and seed errors are intentionally unmapped (not on JSON paths).
- `src/app/features/core/auth/endpoints/auth.py` -- returns `domain_error_response(...)` directly (`/refresh` clears cookies on it); keep that path.
- `src/app/features/core/auth/endpoints/dependencies.py:163` -- `HTTPException(404)` for unknown provider; leave, the handler maps it.
- `src/app/features/core/auth/services/login_service.py:39-58` -- raises/returns `AccountLockedError(lockout_minutes)`; has `user.login_locked_until` and `now`.
- `src/app/features/core/auth/schemas/auth.py` -- `passwords_match` model validators (loc is body root today); `code` uses `pattern`.
- `tests/test_login.py:271` -- asserts no `retry-after` on 423; must change.
- `tests/test_openapi.py` -- pins tags; add error-doc assertions here.

## Tasks & Acceptance

**Execution:**
- [x] `tests/test_error_responses.py` -- new: every I/O matrix row except account locked, plus OpenAPI checks (no `HTTPValidationError` ref anywhere and the schema gone from components; each route's documented 4xx use `ErrorResponse`; `GET /api/v1/menu/dishes/{dish_id}` 404 lists `DISH_NOT_FOUND`). Unhandled/unmapped cases use a test-only route on a fresh app, called through `ASGITransport(app=..., raise_app_exceptions=False)`: Starlette re-raises after the 500 response, so the default transport fails the test. -- tests first
- [x] `tests/test_login.py` -- 423 now has `retry_after` and `Retry-After`, equal to remaining seconds -- matrix row
- [x] `src/app/common/errors.py`, all `services/exceptions.py` -- move each code to a class attribute; constructors keep messages; `AccountLockedError(retry_after: int, lockout_minutes: int)` sets `retry_after` and keeps today's message from `lockout_minutes` -- docs need codes by class
- [x] `src/app/features/core/auth/services/login_service.py` -- pass remaining seconds (ceil of `login_locked_until - now`) and `lockout_minutes` in both places
- [x] `src/app/features/core/auth/schemas/auth.py` -- move the mismatch check onto `password_confirmation` as a field validator that compares only when `"password" in info.data` (a failed `password` is absent there); text becomes "Passwords do not match."
- [x] `src/app/common/error_responses.py` -- `ErrorResponse`/`ErrorDetail` models; one body builder; unmapped DomainError → generic 500, logged with `logger.error(..., exc_info=error)` (it is often returned, not raised, so `logger.exception` has no traceback); validation translator: check `json_invalid` and `loc == ("body",)` first, otherwise field = `loc` minus its source prefix joined by dots; message from the Design Notes table, filled from `ctx` numbers; `value_error` → `str(ctx["error"])` when `ctx` has `"error"` (own validators), else "Enter a valid email address." (EmailStr sets `ctx["reason"]`); helper building `responses=` from status → error classes, with 422 included only for routes that take input
- [x] `src/app/main.py` -- register handlers: `RequestValidationError`, `starlette.exceptions.HTTPException` (404/405/other → `HTTP_ERROR`, keep `exc.headers`, never return `exc.detail`), `Exception` (generic 500, no own logging: Starlette re-raises and uvicorn logs)
- [x] `src/app/features/core/*/endpoints/*.py` -- `responses=` on every route except `/` and `/health`, listing the errors its service calls and dependencies raise; the two OAuth routes document 404 `NOT_FOUND` and 422

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then it passes, and existing tests asserting domain bodies pass unchanged.
- Given `/openapi.json`, when inspected, then no operation references `HTTPValidationError`, and `/health` still documents 503 with `HealthResponse`.
- Given the frontend's `getApiError`, when it receives any new error body, then it takes the `data.code` branch.

## Design Notes

Messages table (by pydantic `type`): `missing` "This field is required."; `string_too_short` "Must be at least {min_length} characters." ("This field is required." when `min_length` is 1); `string_too_long` "Must be at most {max_length} characters."; `string_pattern_mismatch` "Has an invalid format."; `less_than_equal` "Must be at most {le}."; `greater_than_equal` "Must be at least {ge}."; `enum` "Has an invalid value." (pydantic's `expected` text is not passed on); `uuid_parsing`/`int_parsing` "Has an invalid format."; anything else "Is invalid." HTTP layer: `NOT_FOUND` "Not found."; `METHOD_NOT_ALLOWED` "Method not allowed."; `HTTP_ERROR` the standard status phrase followed by a period.

## Verification

**Commands:**
- `uv run pytest` -- all pass
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- clean

**Manual checks:**
- Local uvicorn on :8000: curl each I/O matrix row and the Swagger 404/422 entries for `/menu/dishes/{dish_id}`.

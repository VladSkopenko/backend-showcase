# 12. One error response format for the whole API

Date: 2026-11-11

## Status

Accepted

## Context

Domain errors already reach the client as `{"code", "message"}`, plus `retry_after` and a
`Retry-After` header when the client has to wait. The frontend
([ADR 10](0010-frontend-in-a-separate-repository.md)) is built around that shape: it branches on
`code` and reads `retry_after` for countdowns. Three other kinds of errors do not follow it:

- Request validation errors come from FastAPI as `{"detail": [{"type", "loc", "msg", "input",
  "ctx"}]}`. The frontend converts them into `VALIDATION_ERROR` itself, keeps only the first `msg`,
  and shows raw pydantic text such as `String should match pattern '^\d{6}$'` to users. The field
  the error belongs to is lost, and `input` echoes back what the user typed, passwords included.
- An unhandled exception is plain-text `Internal Server Error`. A domain error with no status in
  the error map falls back to 500 and returns its own message, which may carry internal details.
- An unknown route or method returns `{"detail": "Not Found"}` or `{"detail": "Method Not Allowed"}`.

`ACCOUNT_LOCKED` has no `retry_after`, although the sign-in form needs it to say how long to wait.
None of the error responses are described in the OpenAPI schema.

## Decision

Every JSON error response from the API has one body:

```json
{"code": "DISH_NOT_FOUND", "message": "No dish with this id exists."}
```

- `code` is a stable `UPPER_SNAKE_CASE` string. Clients branch on it. A released code is never
  renamed or reused for another meaning.
- `message` is an English sentence written for the user. Clients may show it but never parse it.
- `retry_after` (integer, seconds) is present when the client has to wait before retrying, together
  with a `Retry-After` header carrying the same value. This now includes `ACCOUNT_LOCKED`.
- `details` is present only on validation errors.

Validation errors (422) look like this:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Enter a valid email address.",
  "details": [{"field": "email", "message": "Enter a valid email address."}]
}
```

The top-level `message` repeats the first entry of `details`, so a client that shows only
`message` still tells the user what to fix.

`field` is the name the client sent, with nested names joined by dots and list positions as numbers
(`items.0.name`). An error that belongs to no single field, such as a malformed JSON body, has no
`field`. Messages are written by the project. Pydantic's own text, the rejected input and validator
internals never reach the client.

Errors that do not come from a domain error get fixed codes:

| Situation | Status | `code` |
|---|---|---|
| Request fails validation | 422 | `VALIDATION_ERROR` |
| No route matches the path, or the HTTP layer answers 404 (an unknown OAuth provider) | 404 | `NOT_FOUND` |
| The route exists but not for this method | 405 | `METHOD_NOT_ALLOWED` |
| Any other error from the HTTP layer | its status | `HTTP_ERROR` |
| Any unhandled exception, or a domain error with no status | 500 | `SERVER_ERROR` |

A 500 response is always the same: `{"code": "SERVER_ERROR", "message": "Something went wrong."}`.
It reveals nothing about the cause. The exception goes to the log once, with its traceback.
`SERVER_ERROR` matches the code the frontend proxy already uses for its own failures, so the
frontend needs no change. Headers that belong to an error, such as `Allow` on 405, are kept.

All error bodies are built in one place. Endpoints either raise a domain error, or return the
error response themselves when it must carry extra headers or cookies, as `/refresh` does when it
clears the session.

Each endpoint lists in OpenAPI the errors it can return, with one shared `ErrorResponse` schema
and the possible codes per status. Declaring 422 on a route replaces FastAPI's default
`HTTPValidationError` entry.

Two routes stay outside this format, because their caller is not frontend code reading JSON:

- `/` and `/health` answer probes (the deploy gate and the container healthcheck) with their own
  body, including the 503.
- The OAuth login and callback routes are browser navigations. They report failures by
  redirecting to the frontend with `?auth_error=<CODE>`. Those codes follow the same stability rule.

## Alternatives considered

- **RFC 9457, Problem Details for HTTP APIs** (`application/problem+json` with `type`, `title`,
  `status`, `detail`, `instance`). It is supported by Spring and ASP.NET Core, but large public
  APIs such as Stripe, GitHub and Google use their own formats with an error code. Adopting it, even
  with `code` as an extension member, would change every existing error body and the content type
  while the only client already works with `{code, message}`.
- **Keep FastAPI's defaults.** No backend work, but the frontend keeps its own 422 converter, users
  keep seeing pydantic text, and field errors cannot be attached to form inputs.

## Consequences

- The frontend reads one shape and branches on `code` alone. Its converter for `detail` stops being
  used and can be removed. Mapping `details` to form fields is a small optional frontend change.
- The guarantee covers responses produced by the API itself. Errors from the reverse proxy or from
  the frontend's own server (502, 504) do not pass through it, so clients still need a fallback by
  status.
- A new domain error needs a code, a status in its feature's error map, and an entry in the
  OpenAPI responses of the endpoints that raise it.

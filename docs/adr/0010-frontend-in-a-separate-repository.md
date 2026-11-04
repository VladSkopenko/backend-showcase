# 10. The frontend lives in a separate repository

Date: 2026-10-28

## Status

Accepted

## Context

The frontend (menu and booking, order tracker, kitchen screen) is written by another developer in
Next.js. This repository is about the backend and its infrastructure. Keeping both in one place would
tie the frontend to the backend's pipeline: arm64 images, tree-hash promotion and a VM with 12 GB of RAM.

The API authenticates with an `HttpOnly` cookie. A frontend on Vercel (`*.vercel.app`) and an API on
DuckDNS (`*.duckdns.org`) are different sites, because both domains are on the Public Suffix List. A
cookie the API set directly would be third-party, and Safari and Firefox block those by default.

## Decision

- The frontend is a separate Next.js repository with TypeScript, hosted on Vercel. It has its own
  pipeline and environments.
- Browsers reach the API only through the frontend's server-side proxy, Next.js rewrites of `/api/*`.
  To the browser, the API lives on the frontend's own domain.
- The API sets no CORS headers. Its auth cookie is host-only (no `Domain` attribute), `HttpOnly`,
  `Secure` and `SameSite=Lax`, so that when proxied it binds to the frontend's domain. Tokens never go
  to `localStorage`.
- WebSocket connections for the order tracker and the kitchen screen go to the API host directly. The
  planned auth is a short-lived ticket fetched through `/api`, plus an allowlist of `Origin` values; the
  details are settled in the Phase 7 spec.
- The rule that each image is built once ([ADR 4](0004-image-identity-and-promotion.md)) applies to the
  backend image only. Vercel builds the frontend per environment, so the API URL can be set at build time.

## Alternatives considered

- **Frontend in this repository, served from each environment's host.** One origin and no proxy, but
  it adds a Node server or a static file container to every environment on the VM, plus a second
  toolchain to this repository's CI.
- **Direct cross-origin calls with CORS.** Cookie auth breaks in browsers that block third-party
  cookies. Moving the token into JavaScript-readable storage would trade that for exposure to XSS.

## Consequences

- The VM runs only the API, and the backend repository stays focused on the backend.
- The API contract (OpenAPI schema, cookie attributes, WebSocket auth) is the only thing the two
  repositories share. Changes to it have to be announced to the frontend.
- Developing the frontend against a live API needs the dev environment from Phase 3. Until then it
  needs a local backend or mocks.

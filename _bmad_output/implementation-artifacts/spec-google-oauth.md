---
title: 'Sign in with Google'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_commit: '2007d113a993baf46f158c558fe539d2eabfa062'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-login-jwt-sessions.md'
  - '{project-root}/_bmad_output/planning-artifacts/architecture/architecture-backend-showcase-2026-10-28/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Users can sign in only with a password. A "Sign in with Google" button sits next to the sign-in and registration forms (it is not in the Figma file), and the backend has no OAuth flow behind it.

**Approach:** Authorization-code flow with OpenID Connect through a provider registry, Google as its only member: `GET /api/v1/auth/{provider}/login` redirects to Google, `GET /api/v1/auth/{provider}/callback` resolves or creates the user, starts our usual session in cookies and redirects to the frontend. Story 5 of 5 on `feature/auth-reset-oauth`.

## Boundaries & Constraints

**Always:**
- Decision (Vlad): a provider registry. `OAuthProvider` enum (`GOOGLE`, uppercase per backend.md; the URL uses the lowercase slug `google`); a provider class per provider turns the provider's claims into one `OAuthIdentity` (`subject`, `email`, `email_verified`, `first_name`, `last_name`); adding a provider means a member, a class and a client registration, nothing else. Boolean claims are read as true only for JSON `true` or the string `"true"`.
- Decision (Vlad): the session is our pair of cookies set by `SessionCookies` on the callback redirect, never tokens in the URL or a fragment.
- Decision (Vlad): both routes are reached through the frontend proxy (AD-19). The redirect URI sent to Google is `{APP_FRONTEND_URL}/api/v1/auth/{slug}/callback`, built from settings, never from the request host, so the state cookie and the session cookies land on the frontend's domain. The button is a top-level navigation to `{APP_FRONTEND_URL}/api/v1/auth/google/login`.
- Resolution order on callback: 1) a stored link `(provider, subject)` → that user; 2) otherwise, only if `email_verified` is true, the user with that email → link it; 3) otherwise, if `email_verified` is true, create a user → link it; 4) otherwise refuse. `sub` is the identity key, email only matches once.
- Decision (Vlad, spec review): a user has at most one link per provider (unique `(user_id, provider)`). In step 2, a user who already has a link to another subject of that provider is refused with `OAUTH_ACCOUNT_CONFLICT` and nothing is written, so a reassigned address cannot take over an account that is already tied to its owner's Google account.
- Decision (Vlad): linking to an unverified account sets `email_verified_at` and wipes `password_hash` (whoever pre-registered the address loses the password; the owner can set one through password reset). Linking to a verified account keeps its password.
- Decision (Vlad): a new user is created verified, without a password, names from `given_name` / `family_name`. Accepted default: a missing `given_name` falls back to `name`, then to the email's local part; a missing `family_name` is an empty string; both cut to 100 characters.
- Accepted default: Google sign-in ignores the password lockout and leaves its counter untouched.
- Accepted default: success redirects to `{APP_FRONTEND_URL}/`; every failure redirects to `{APP_FRONTEND_URL}/?auth_error=<CODE>` with no session cookies: `OAUTH_CANCELLED` (provider returned `error=access_denied`), `OAUTH_EMAIL_UNVERIFIED` (no link and `email_verified` false or no email), `OAUTH_ACCOUNT_CONFLICT` (above), `OAUTH_UNAVAILABLE` (provider not configured), `OAUTH_FAILED` (state mismatch, missing state cookie, no ID token, token exchange or validation failure, provider metadata unreachable, any other provider error). An unknown slug is 404 on both routes.
- The service decides every error code: the endpoint hands it either the claims or the caught exchange failure, and it checks whether the provider is configured.
- OAuth state, nonce and PKCE verifier live in a signed cookie from Starlette `SessionMiddleware`: name `oauth_state`, `same_site="lax"`, `https_only=True`, secret `TOKEN_SECRET_KEY`, path `AuthSettings.oauth_state_cookie_path` (default `/api/v1/auth`), `max_age` `AuthSettings.oauth_state_max_age_seconds` (default 600). Every callback exit, success or failure, empties the session so the cookie is deleted. Scope `openid email profile`; the email and its verification come from the ID token that the client validates against Google's keys and the nonce.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (`GoogleSettings`, already in `settings.py` and `.env.example`) live in the `dev` GitHub Environment; the agent wires them through compose and delivery like the email secrets (optional: empty means the provider is unavailable).

**Never:** tokens in URLs, CORS, an `APP_BACKEND_URL`-based callback, Apple/Facebook/LinkedIn or any second provider, a draft or registration-completion step, unlinking or account settings, provider access/refresh token storage, changes to password login, registration or reset rules, IP rate limiting.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Start | `GET /google/login`, Google configured | 302 to Google with `redirect_uri` `{frontend}/api/v1/auth/google/callback`, `state`, `nonce`, PKCE `S256`; `oauth_state` cookie with the attributes above | N/A |
| Unconfigured | client id or secret empty, either route | 302 to `/?auth_error=OAUTH_UNAVAILABLE`, no state cookie | N/A |
| Metadata unreachable | `/login` cannot load Google's metadata | 302 to `/?auth_error=OAUTH_FAILED` | N/A |
| Unknown provider | `GET /github/login` or `/github/callback` | 404 | N/A |
| Linked user | link `(GOOGLE, sub)` exists | 302 to `/`; both session cookies; refresh row created; lockout ignored; `oauth_state` deleted | N/A |
| Verified email, verified account | no link, account verified, no Google link | link stored; password kept; 302 to `/` with cookies | N/A |
| Verified email, unverified account | no link, account unverified | link stored; `email_verified_at` set; `password_hash` null; 302 to `/` with cookies | N/A |
| Verified email, no account | no link, no user | user created (verified, no password, names per fallback), link stored, 302 to `/` with cookies | N/A |
| Conflicting link | no link for this sub, email matches a user linked to another Google sub | 302 to `/?auth_error=OAUTH_ACCOUNT_CONFLICT`; nothing written | N/A |
| Unverified Google email | no link, `email_verified` false or missing email | 302 to `/?auth_error=OAUTH_EMAIL_UNVERIFIED`; nothing written | N/A |
| Cancelled | callback with `error=access_denied` | 302 to `/?auth_error=OAUTH_CANCELLED`; `oauth_state` deleted | N/A |
| Bad state | no or tampered `oauth_state` cookie, state mismatch, no ID token, exchange or validation failure | 302 to `/?auth_error=OAUTH_FAILED`; nothing written | N/A |
| Password after Google | user created by Google tries password login | 401 `INVALID_CREDENTIALS` until a reset sets a password | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/main.py` -- `create_app`; add `SessionMiddleware` here (main may import starlette).
- `backend/src/app/config/settings.py` -- `GoogleSettings` (Vlad's; add an `is_configured` property: both values non-empty), `AuthSettings`, `TokenSettings.secret_key`.
- `backend/src/app/features/core/auth/endpoints/auth.py`, `cookies.py`, `dependencies.py` -- `SessionCookies.set(response=, session=)` works on any returned `Response`, including `RedirectResponse`; providers live in `dependencies.py`.
- `backend/src/app/features/core/auth/services/session_service.py` -- `start(user=)` issues the pair.
- `backend/src/app/features/core/users/repositories/user_repository.py` -- `get_by_email(for_update=True)`, `add`. `User.email` is normalised by a validator; `password_hash` is nullable; `LoginService.log_in` already answers `INVALID_CREDENTIALS` for a null hash.
- `backend/src/app/infrastructure/email/` -- pattern for an infrastructure client injected through an endpoint dependency. `app.infrastructure.*` is outside the "no fastapi/starlette" contract (only `background_tasks` is in it), so the authlib Starlette client belongs there; feature services stay free of it.
- `backend/src/app/model_registry.py`, `backend/migrations/versions/0004_add_password_reset.py` -- register the model; 0005 follows 0004. `common/database.py:16`: `uq` and `ix` conventions use the first column only, so composite names are explicit.
- `backend/pyproject.toml` -- `httpx2` is only in the `dev` group, `filterwarnings = ["error"]`; `backend/Dockerfile:10,12` installs with `--no-dev`.
- `backend/tests/conftest.py` -- clears `APP_`/`EMAIL_`/`AUTH_`/`TOKEN_` env; add `GOOGLE_`.
- `deploy/app/compose.yml:37-41`, `.github/workflows/delivery.yml:130-140` -- email secrets: `${VAR:-}` in compose, env + `printf` line over SSH stdin in delivery.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/pyproject.toml`, `backend/uv.lock` -- `uv add authlib itsdangerous httpx2` (`httpx2` moves from dev to runtime: authlib imports it and falls back to `httpx` with a deprecation warning that `filterwarnings = ["error"]` turns into a failure; `SessionMiddleware` needs `itsdangerous`).
- [ ] `backend/tests/test_google_oauth.py` -- every matrix row through the HTTP API with the `OAuthClients` dependency overridden by a fake (no network); the fake writes `request.session` so `oauth_state` set and delete headers are asserted from raw `Set-Cookie`; database state asserted for links, names, `password_hash`, `email_verified_at`.
- [ ] `backend/tests/test_oauth_clients.py` -- the real `OAuthClients` with no network: inline metadata (`authorize_url`, `access_token_url`, `issuer`, `jwks`) instead of the metadata URL, an ID token signed with joserfc, the token endpoint on an `httpx2.MockTransport`; covers `state`, `nonce`, PKCE `S256`, `redirect_uri` in the authorize URL, state mismatch, `access_denied`, missing ID token, bad signature.
- [ ] `backend/tests/test_oauth_providers.py` -- Google claims to `OAuthIdentity`: name fallbacks, 100-character cut, boolean claim spellings, missing `sub`.
- [ ] `backend/tests/test_database.py`, `test_settings.py` -- new table, enum, both unique constraints; `GOOGLE_*` mapping, `is_configured`, `AUTH_OAUTH_STATE_MAX_AGE_SECONDS`, `AUTH_OAUTH_STATE_COOKIE_PATH`.
- [ ] `backend/migrations/versions/0005_add_oauth_accounts.py` -- enum `oauth_provider` (`GOOGLE`) and table `user_oauth_accounts`: `id` uuid, `user_id` FK `ondelete=CASCADE` indexed, `provider`, `subject` `String(255)`, `created_at` (service clock); unique `uq_user_oauth_accounts_provider_subject` and `uq_user_oauth_accounts_user_id_provider`. Downgrade drops the table, then the type.
- [ ] `backend/src/app/features/core/auth/enums/oauth_provider.py`, `models/oauth_account.py`, `repositories/oauth_account_repository.py`, `model_registry.py` -- enum with a `slug`; model; get by `(provider, subject)`, get by `(user_id, provider)`, add.
- [ ] `backend/src/app/features/core/auth/dto/oauth_identity.py`, `dto/oauth_sign_in_outcome.py` -- identity; outcome with `session` or `error`.
- [ ] `backend/src/app/features/core/auth/services/oauth_providers/` -- `base.py` (abstract provider: `identity(claims)`), `google.py`, `registry.py` (`OAuthProviderRegistry`: enum → provider instance).
- [ ] `backend/src/app/features/core/auth/services/oauth_sign_in_service.py`, `exceptions.py` -- `complete(provider=, claims=, failure=)` style entry: configured check, failure to code (`cancelled` → `OAUTH_CANCELLED`, else `OAUTH_FAILED`), resolution order, linking rules, user creation; five `OAUTH_*` errors returned in the outcome. A `start` check gives `OAUTH_UNAVAILABLE` before `/login` redirects.
- [ ] `backend/src/app/infrastructure/oauth/` -- `OAuthClients`: registers authlib clients for configured providers (Google: `server_metadata_url` `https://accounts.google.com/.well-known/openid-configuration`, scope, PKCE `S256`); `authorize_redirect(request=, provider=, redirect_uri=)`; `fetch_claims(request=, provider=)` returning the validated ID token claims. Every exception from metadata loading, the exchange or validation, and a missing `userinfo`, becomes `OAuthExchangeError` with `cancelled` set for `access_denied`; both methods empty `request.session` on failure, `fetch_claims` also on success.
- [ ] `backend/src/app/features/core/auth/endpoints/` -- `oauth.py` router with the two routes; `dependencies.py` resolves the slug to `OAuthProvider` (404 otherwise) and provides `OAuthClients` and the service; `oauth_redirects.py` (`OAuthRedirects`: success and error URLs from `frontend_url`); router mounted with the auth router.
- [ ] `backend/src/app/main.py`, `config/settings.py`, `backend/.env.example` -- middleware; `oauth_state_max_age_seconds`, `oauth_state_cookie_path`; `GoogleSettings.is_configured`.
- [ ] `deploy/app/compose.yml`, `.github/workflows/delivery.yml` -- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` from the `dev` Environment to the `api` service.
- [ ] `ARCHITECTURE-SPINE.md` AD-19 -- OAuth routes are top-level navigations through the proxy; the rewrite must pass 302 responses and `Set-Cookie` through without following them.

**Acceptance Criteria:**
- Given the dev deploy with the Google secrets and `https://family-rest.vercel.app/api/v1/auth/google/callback` among the client's authorized redirect URIs, when Vlad opens `https://family-rest.vercel.app/api/v1/auth/google/login` and consents, then the browser lands on the frontend with both session cookies and `GET /api/v1/auth/me` returns his profile.
- Given CI and the built image, then lint, mypy, import-linter, the migration round-trip with `alembic check`, actionlint and tests pass, and the image starts (`httpx2` installed without the dev group).

## Implementation Notes

- Dependencies were installed by Vlad (authlib 1.9.5, joserfc 1.8.0, itsdangerous). authlib ships no `py.typed`, so `pyproject.toml` has a mypy override `authlib.*` with `ignore_missing_imports = true`.
- Test seams on `OAuthClients`: `server` (per-provider inline metadata replacing the metadata URL) and `client_kwargs` (merged into authlib's `client_kwargs`, e.g. an `httpx2.MockTransport`).
- Verified in the installed authlib 1.9.5 source and by `tests/test_oauth_clients.py` (8 passed):
  - `transport` in `client_kwargs` reaches the httpx2 client: `AsyncOAuth2Client` keeps every key listed in `httpx_client/utils.py` `HTTPX_CLIENT_KWARGS`, `transport` included, and passes them to `httpx2.AsyncClient.__init__`.
  - `StarletteAppMixin.authorize_redirect` returns `RedirectResponse(url, status_code=302)` after saving `redirect_uri`, `nonce` and `code_verifier` in `request.session`.
  - Extra `register` kwargs (`issuer`, `jwks`) become `server_metadata` (`OAuth2Base.__init__`: `self.server_metadata = kwargs`). The metadata URL is fetched only when `server_metadata_url` is set. `parse_id_token` checks `iss` against `metadata["issuer"]` and takes the keys from `metadata["jwks"]` before falling back to `jwks_uri`.
  - `authorize_access_token` raises `OAuthError(error=<query error>)` before touching the state, so `access_denied` arrives as `error.error`. Missing state data raises `MismatchingStateError` (an `OAuthError`, `error="mismatching_state"`), which becomes `OAUTH_FAILED`. `token["userinfo"]` is set only when an `id_token` came back.
  - The bad-signature test differs from the passing success test only in the signing key, so its failure comes from the signature check.
- `test_oauth_clients.py`: the `FakeGoogle.key` dataclass default became `field(default_factory=...)`. Dataclasses reject a non-hashable `RSAKey` as a plain default. `oauth_clients.py` needed no change.
- The service is `OAuthSignInService`: `start(provider=)` returns `OAUTH_UNAVAILABLE` or `None`, `failure_error(failure=)` maps an `OAuthExchangeError`, `complete(provider=, claims=, failure=)` resolves the user. `OAuthExchangeError` lives in `app.infrastructure.oauth.oauth_exchange_error`, a module free of starlette, so the service can import it without breaking the HTTP contract.
- `OAuthClients` is built once per app in `create_app` and kept on `app.state.oauth_clients`; `get_oauth_clients` returns it. authlib caches the provider metadata and JWKS only on the client instance, so a per-request instance would refetch both on every `/login` and `/callback`.
- `OAuthClients` is keyed by the provider slug (`provider_slug: str`, `server` keyed by slug), so `app.infrastructure` imports no feature; the endpoints pass `provider.slug`.
- Configured-ness lives on the provider class (`OAuthIdentityProvider.is_configured`), built by `OAuthProviderRegistry` from `GoogleSettings`.
- The callback redirect URI path comes from `app.url_path_for(OAuthRedirects.CALLBACK_ROUTE, ...)`, joined to `APP_FRONTEND_URL`.

## Spec Change Log

- 2026-11-09, spec review: Vlad chose to refuse a second link per provider (`OAUTH_ACCOUNT_CONFLICT`, unique `(user_id, provider)`); `httpx2` becomes a runtime dependency; the service owns every error code; exchange failures are wrapped; a no-network test of the real client was added; every callback exit clears the state cookie; its path moved to settings. Known-bad states avoided: an image that crashes on import while tests pass; 422 for every slug; error decisions in route handlers; untested state/nonce/PKCE; a reassigned address silently gaining a second link.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | `httpx2` is dev-only, authlib imports it; image crashes at startup | high | PyPI `requires_dist` (cryptography, joserfc); authlib `httpx_client/_compat.py`; `pyproject.toml:131`; `Dockerfile:10,12`. Patched. |
| 2 | spec review | Enum path parameter cannot give 404 for a lowercase slug | high | FastAPI validates enum values (`GOOGLE`), so `google` gets 422. Patched: dependency resolves the slug. |
| 3 | spec review | Error code choice and the configured check would land in the handler | medium | backend.md: decisions belong to services. Patched; metadata failure added. |
| 4 | spec review | Exceptions to wrap and the no-ID-token case unspecified | medium | authlib sets `userinfo` only with `id_token` and nonce. Patched. |
| 5 | spec review | Faked client leaves state, nonce, PKCE untested | medium | Patched: `test_oauth_clients.py`. |
| 6 | spec review | Second Google link for a user undefined | medium | Vlad: refuse. Patched. |
| 7 | spec review | `oauth_state` survives cancelled and unconfigured callbacks | low | authlib raises before `clear_state_data` on `error`. Patched. |
| 8 | spec review | Cookie path literal against backend.md | low | Patched: setting. |
| 9 | spec review | `TOKEN_SECRET_KEY` also signs the state cookie | low | itsdangerous derives its own key, so JWTs cannot be forged; rotation drops in-flight OAuth flows. Noted in Design Notes. |
| 10 | verification-gap, blind | `OAuthClients` built per request; authlib caches metadata and JWKS per instance, so every sign-in refetches them | medium | `get_oauth_clients` returned a new instance; authlib `async_app.py` `load_server_metadata`. Patched: one instance per app on `app.state`. |
| 11 | blind | `app.infrastructure.oauth` imports the auth feature enum; the service imports infrastructure back | low | `oauth_clients.py` imports `OAuthProvider`; `infrastructure/email` imports no feature. Patched: clients keyed by slug string; a test pins `OAuthClients.GOOGLE_SLUG` to `OAuthProvider.GOOGLE.slug`. |
| 12 | verification-gap | Real `get_oauth_clients` wiring never resolved by an app test | medium | Every app test overrides it. Defer: the dev live sign-in covers it. |
| 13 | verification-gap, edge | Concurrent first sign-in answers 500 | low | Accepted as rare in Design Notes. Rejected. |
| 14 | edge | Double-submitted callback answers `OAUTH_ACCOUNT_CONFLICT` | false | The second request reuses the authorization code, which Google rejects at the exchange, so it ends in `OAUTH_FAILED` before `_resolve_user`. |
| 15 | edge | Names chosen by a pre-registrant stay when the owner claims the account through Google | low | `_resolve_user` changes only `email_verified_at` and `password_hash`. Rare pre-hijack case; raised with Vlad. Rejected for this story. |
| 16 | edge | Unexpected exceptions in `complete` answer 500 JSON instead of a redirect | low | Database failures answer 500 on every route. Rejected. |
| 17 | edge | `httpx2` listed in both runtime and dev | low | Harmless duplicate from Vlad's `uv add`; dependency lists are his. Raised with Vlad. |
| 18 | blind | `joserfc` imported by tests, only transitive through authlib | low | `test_oauth_clients.py`. Raised with Vlad (`uv add --dev joserfc`). |
| 19 | blind | OAuth decisions not in an ADR | low | workflow.md rule 5. Defer: auth ADR batch. |
| 20 | blind | `email_verified` may not prove current ownership of a non-Google domain address | maybe-false | Frozen decision links on `email_verified`; the reviewer cited Google guidance from memory. Defer: check Google's guidance on `hd` and non-Gmail addresses. |
| 21 | blind | Outcome type allows impossible states; handler asserts | false | Same outcome-and-assert pattern accepted in the login spec (Implementation Notes). |
| 22 | blind | `/login` takes a database connection | false | `AsyncSession` checks out a connection only on the first statement; `start` runs none, and committing an unused session is a no-op. |
| 23 | blind | `ix_user_oauth_accounts_user_id` duplicates the `(user_id, provider)` unique index | low | The task asked for an indexed FK; extra write cost on a small table. Rejected. |
| 24 | blind | Unknown slug answers `{"detail"}`, not `{"code","message"}` | low | Matches the 404 the spec asks for; the 422 shape is already deferred. Rejected. |
| 25 | blind | OAuth sign-in over another user's session leaves the old refresh token active | low | Same as login row 29. Rejected. |
| 26 | blind | Test gaps: verified-user conflict, deleted linked user, unknown slug on callback, state reuse via HTTP | low | Same branches covered by the unverified conflict test and `test_oauth_clients.py` mismatch tests. Rejected. |

## Design Notes

- Verified in source: Starlette 1.10.0 `SessionMiddleware` signs with `itsdangerous`, writes the cookie only when the session was modified and is non-empty, deletes it (`expires=1970`, same path) when emptied, and treats a bad or expired signature as an empty session.
- Authlib 1.9.5 (PyPI and GitHub source, read by subagents): depends only on `cryptography` and `joserfc`; its httpx integration imports `httpx2` and falls back to `httpx` with a deprecation warning. `authorize_redirect` keeps `redirect_uri`, `nonce` and the PKCE verifier in `request.session`; `authorize_access_token` reuses that `redirect_uri`, raises `OAuthError` when the provider sent `error` (before touching the state), `MismatchingStateError` when the state data is missing, and sets `token["userinfo"]` only when an `id_token` came back. It loads the metadata URL over the network on first use. Unverified: whether `client_kwargs` passes a `transport` to the `httpx2` client; if not, the real-client test patches the client class and says so in Implementation Notes.
- Google (OpenID Connect docs): `sub` is the stable identifier, `email` may change; `email` and `email_verified` come with the `email` scope; `name`, `given_name`, `family_name` are never guaranteed. Redirect URIs must match exactly, scheme, case and trailing slash included.
- `TOKEN_SECRET_KEY` signs the state cookie through itsdangerous's own derived key; rotating it ends OAuth flows started before the rotation.
- Unverified: whether the Next.js rewrite on Vercel passes upstream 302 and `Set-Cookie` to the browser; the docs only call rewrites a proxy. The dev acceptance check settles it.
- A concurrent first sign-in of the same new Google account can hit `uq_users_email` or a link constraint and answer 500; the next attempt finds the link. Accepted as rare.
- Local live check needs `APP_FRONTEND_URL=http://localhost:8000` and `http://localhost:8000/api/v1/auth/google/callback` among the authorized redirect URIs.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.
- On a throwaway `postgres:18` (data in tmpfs, no volume): `alembic upgrade head`, `downgrade 0004`, `upgrade head`, `alembic check` -- clean.
- `actionlint .github/workflows/*.yml` and `docker compose -f deploy/app/compose.yml config --quiet` with the variables set -- clean.
- `docker build backend` and an import of `app.main` inside the image -- succeeds without the dev group.

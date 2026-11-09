---
title: 'Menu: dishes with pictures in Object Storage'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_commit: '3aacad119219b9674520eaf1383ee14f48dff7ac'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/docs/adr/0011-feature-sliced-backend-layout.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-openapi-flow-tags.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Figma "Menu" page (tabs Appetizers / Main Courses / Desserts, "Sort by" Popular First / Newest First / Price: Low to High / Price: High to Low, dish cards with picture, name, price, weight, "Sold Out") and its dish modal (description, calories, protein, fats, carbs, vitamins) have no backend.

**Approach:** A regular feature `menu` with two read routes, `GET /api/v1/menu/dishes` and `GET /api/v1/menu/dishes/{id}`. Dish metadata lives in PostgreSQL; pictures live in OCI Object Storage, written through the S3 Compatibility API by a file-storage repository. Dishes are filled by a seed script for now.

## Boundaries & Constraints

**Always:**
- Decision (Vlad, 2026-11-09): pictures live in OCI Object Storage, one public-read bucket per environment (`backend-showcase-media-<env>`, anonymous download, no listing), created by `deploy/terraform/object_storage.tf`. All code talks S3 (boto3) to it; local development uses the dev bucket with keys in `backend/.env`. No local emulator, no fake storage.
- Decision (Vlad): file access goes through a repository-like class in `app/infrastructure/storage/` (`S3FileStorage.put(key=, content=, content_type=)`; no delete, nothing removes dishes), constructed from `MediaSettings`. Only the seed writes; the read API never calls the bucket. boto3 is configured for OCI: path-style addressing, `signature_version="s3v4"`, and `request_checksum_calculation="when_required"` / `response_checksum_validation="when_required"` (botocore 1.36+ sends checksums by default that OCI rejects; reported by the spec review from Oracle's S3 compatibility docs, confirmed by the first live upload).
- The database stores the object key (`dishes/<slug>.<ext>`), never a full URL. Responses carry `image_url` = `MEDIA_PUBLIC_BASE_URL` (required setting, trailing slash stripped) + `/` + key, built by the catalog service from the one setting it receives, so moving the bucket or adding a CDN needs no data migration.
- Dish columns: `id` (uuid), `slug` (unique), `name`, `description`, `category` (enum `APPETIZER`, `MAIN_COURSE`, `DESSERT`), `price_cents` (int > 0), `weight_grams` (int > 0), `calories` (int), `protein`, `fats`, `carbs` (short strings as the cook writes them, e.g. `18-20g`), `vitamins` (string), `is_available` (bool, "Sold Out" when false), `popularity` (int, default 0), `image_key`, `created_at`, `updated_at`.
- Decision (Vlad): `popularity` is a counter. The seed sets it only when it inserts a dish; a later orders story increments it by the dish quantity in the transaction that marks an order paid. Indexed for sorting.
- List: filter `category` (optional), `sort` = `POPULAR` (popularity desc) | `NEWEST` (created_at desc) | `PRICE_ASC` | `PRICE_DESC`, default `POPULAR`; every sort breaks ties by `id` so pages are stable. Decision (Vlad, code review): pagination `limit` is a fixed part of the API contract, `Query(ge=1, le=50)` with default 20 on a plain module router (no settings, no router factory), and `offset`; the response is `{"items": [...], "total": N, "limit": L, "offset": O}`. Unavailable dishes are listed too (the design greys them out).
- Decision (Vlad): a list item is the card plus popularity: `id`, `name`, `category`, `price_cents`, `weight_grams`, `is_available`, `popularity`, `image_url`. The item route adds `description`, `calories`, `protein`, `fats`, `carbs`, `vitamins`. `slug`, `image_key` and timestamps are not exposed; enums serialise as their uppercase values.
- Item: `GET /dishes/{id}` returns the full dish; unknown id → 404 `DISH_NOT_FOUND`.
- Both routes are public (no session) and documented under a "Menu" OpenAPI tag per the API docs convention.
- Seed: `uv run python -m app.scripts.seed_menu <dir>` reads `<dir>/dishes.json` (each entry names its picture in `image`; content type from the extension: `.webp`, `.jpg`, `.png`), validates the whole file before any upload, uploads every picture under `dishes/<slug>.<ext>` on every run, and upserts by `slug`: a new dish gets `popularity` from the file and `created_at` stepping back one minute per position in the file (the first entry is the newest); an existing dish gets its content fields updated and keeps `id`, `popularity` and `created_at`. Dishes missing from the file stay. The logic is `DishSeedService` in `features/menu/services/` (session and `S3FileStorage` injected); `app/scripts/seed_menu.py` only builds settings, the session and the storage, runs it and commits. An import contract keeps `app.scripts` unimported by the rest of `app`. The seed needs the `MEDIA_*` write keys; the API needs only `MEDIA_PUBLIC_BASE_URL`.
- boto3 is a dev dependency (with `boto3-stubs[s3]` or a mypy override): only the local seed uses it, so the runtime image does not ship it.
- Tests: the API, the JSON parsing and the database upsert are tested; the upload to the bucket is checked live on dev only (no fakes).

- Decision (Vlad, 2026-11-09, changed during code review): the seed data lives in `backend/seed/menu/` (`dishes.json` plus one compressed picture per dish) on the developer machine only; `backend/seed/` is git-ignored. The seed runs from the developer's machine: `DATABASE_*` point at the dev database through an SSH tunnel to the VM, and the `MEDIA_*` write keys live only in the local `backend/.env`, never on the server. The image does not ship the seed folder.

**Never:** writes through the API, admin endpoints, carts, orders, locations, dietary badges, image resizing, signed URLs, a fake or local storage backend, full URLs in the database, write keys on the VM.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| List default | no params | 200, first 20 dishes by popularity desc, `total` = all dishes | N/A |
| Filter | `category=DESSERT` | only desserts; `total` counts desserts | N/A |
| Sort | each `sort` value | order as defined, ties by id | N/A |
| Page | `limit=2&offset=2` | items 3–4; same `total` | N/A |
| Past the end | offset ≥ total | 200, empty `items`, real `total` | N/A |
| Bad params | `limit=0`, `limit=51`, `offset=-1`, unknown `sort` or `category` | 422 | N/A |
| Item | known id | 200 full dish with `image_url` | N/A |
| Unknown item | random uuid | 404 `DISH_NOT_FOUND` | N/A |
| Sold out | `is_available=false` | listed, `is_available: false` | N/A |
| Seed twice | same directory, a dish's popularity changed in the database | same rows, no duplicates; popularity and created_at kept | N/A |

</frozen-after-approval>

## Code Map

- `backend/src/app/features/` -- only `core/` exists; `menu` is the first regular feature. Import contracts in `backend/pyproject.toml` already cover `app.features.*` (independence, layers, no HTTP below endpoints).
- `backend/src/app/features/core/auth/` -- reference layout: `models/`, `repositories/` (class with session, `flush()` only), `services/` (constructor injection, `exceptions.py`), `dto/`, `enums/`, `schemas/`, `endpoints/` (`dependencies.py`, `errors.py`, `openapi_tags.py`).
- `backend/src/app/infrastructure/email/` -- pattern for an infrastructure client chosen from settings.
- `backend/src/app/config/settings.py` -- add `MediaSettings` (`MEDIA_` prefix: `s3_endpoint_url`, `region`, `bucket`, `access_key_id`, `secret_access_key: SecretStr`, `public_base_url`); register it on `Settings`.
- `backend/src/app/main.py` -- mount the menu router under `/api/v1`, merge its error statuses and OpenAPI tag.
- `backend/src/app/model_registry.py`, `backend/migrations/versions/` -- migration `0006` after `0005`.
- `backend/tests/conftest.py` -- clears env prefixes for tests; add `MEDIA_`. API tests insert dishes directly through the session factory.
- `backend/tests/test_openapi.py` -- `FLOWS` must gain the Menu tag and both routes.
- `deploy/terraform/object_storage.tf`, `outputs.tf` -- bucket, writer user and key; outputs give the endpoint, public base URL and keys.
- `deploy/app/compose.yml`, `.github/workflows/delivery.yml` -- `MEDIA_PUBLIC_BASE_URL` for the dev `api` (a plain value, not a secret).

## Tasks & Acceptance

**Execution:**
- [ ] `backend/pyproject.toml`, `backend/uv.lock` -- `uv add --dev boto3 "boto3-stubs[s3]"` (Vlad runs it if the agent is blocked); import contract: nothing in `app` imports `app.scripts`.
- [ ] `backend/tests/test_menu.py` -- every matrix row through the HTTP API except the seed row.
- [ ] `backend/tests/test_seed_menu.py` -- JSON validation (a bad entry fails before anything is written), key derivation, and the database upsert: insert, then a second run with a changed popularity in the database keeps popularity and created_at.
- [ ] `backend/tests/test_database.py`, `test_settings.py`, `test_openapi.py` -- table, enum and indexes; `MEDIA_*`; the Menu tag.
- [ ] `backend/migrations/versions/0006_create_dishes.py` -- enum `dish_category`, table `dishes`, unique `slug`, indexes for `(category, popularity)`, `popularity`, `created_at`, `price_cents`.
- [ ] `backend/src/app/features/menu/` -- `enums/` (`DishCategory`, `DishSort`), `models/dish.py`, `repositories/dish_repository.py` (page query with filter, sort, count; upsert by slug), `dto/` (page, dish view with `image_url`, seed entry), `services/` (`DishCatalogService`, `DishSeedService`, `exceptions.py`), `schemas/`, `endpoints/` (router, dependencies, errors, `openapi_tags.py`).
- [ ] `backend/src/app/infrastructure/storage/` -- `S3FileStorage` with boto3, path-style addressing, region from settings.
- [ ] `backend/seed/menu/dishes.json` and pictures -- prepared by the orchestrating session, not the implementer: 10 dishes per category (30), the 9 Figma photos plus 21 generated in a separate Figma file, square 640 px JPEG of about 90 KB each (macOS `sips` cannot write WebP). The implementer writes the seed code and tests against a small fixture of its own.
- [ ] `backend/src/app/scripts/seed_menu.py` -- CLI per the seed rule.
- [ ] `backend/src/app/config/settings.py`, `main.py`, `model_registry.py`, `backend/.env.example`.
- [ ] `deploy/app/compose.yml`, `.github/workflows/delivery.yml` -- `MEDIA_PUBLIC_BASE_URL`.

**Acceptance Criteria:**
- Given the dev bucket from Terraform and the seed run locally through the SSH tunnel, when the frontend calls `GET /api/v1/menu/dishes?category=APPETIZER&sort=PRICE_ASC`, then dishes come back in price order and every `image_url` opens the picture in a browser.
- Given CI, then lint, mypy, import-linter, the migration round-trip with `alembic check`, and tests pass.

## Implementation Notes

- Live check 2026-11-09 (local database, dev bucket): `seed_menu seed/menu` uploaded 30 pictures and upserted 30 dishes; PutObject works with path-style, s3v4 and checksums when_required; the native public URL `https://objectstorage.eu-frankfurt-1.oraclecloud.com/n/fr76arfm8eim/b/backend-showcase-media-dev/o/<key>` answers 200 `image/jpeg` anonymously, the bucket listing answers 404; `GET /api/v1/menu/dishes?category=APPETIZER&sort=PRICE_ASC&limit=3` and `GET /dishes/{id}` return the documented shapes, an unknown id 404. The Terraform API key needed `manage users` and `manage groups` in the tenancy (policy `backend-showcase-terraform-iam`, created by Vlad).

## Spec Change Log

- 2026-11-09, code review: Vlad replaced the settings-driven page size (which forced a router factory) with a fixed `limit` of 20 by default and 50 at most; `MenuSettings` and `MENU_*` removed. Known-bad state avoided: an unreadable router factory inconsistent with the other features.

- 2026-11-09, code review: Vlad moved the seed data out of git (`backend/seed/` in `.gitignore`); pictures are JPEG, not WebP. KEEP: the seed format, the loader and every test that builds its own fixture.

- 2026-11-09, spec review: boto3 configured for OCI (path-style, s3v4, checksums when required); seed upsert keeps popularity, created_at and id, and orders created_at by file position; seed logic moved to `DishSeedService` with a thin script and an import contract; response fields listed, popularity included in the list (Vlad); `MEDIA_PUBLIC_BASE_URL` required; `limit` bound read when the router is built; no delete in storage; boto3 dev-only; Terraform users get an email, the tenancy comes from the compartment's parent, the region from one local. Known-bad states avoided: PutObject rejected by OCI; reseeding wiping real popularity; NEWEST degenerating to uuid order; `apply` failing on users without email.

## Review Triage Log

| # | Source | Finding | Verdict | Evidence / route |
|---|--------|---------|---------|------------------|
| 1 | spec review | boto3 checksum defaults break PutObject on OCI | high | Oracle S3 compatibility docs as cited by the reviewer; unverified here, the first upload confirms. Patched. |
| 2 | spec review | Identity-domain users need an email; apply would fail | high | Reviewer-cited provider and domain docs; unverified here. Patched: `media_writer_email`. |
| 3 | spec review | Reseeding resets popularity; `updated_at` churn | high | Upsert semantics undefined. Patched. |
| 4 | spec review | Seed logic has no home under backend.md | medium | `app.scripts` not in ADR 0011 or contracts. Patched: `DishSeedService`, thin script, import contract. |
| 5 | spec review | Seed row and storage untested; fake ambiguity | medium | Vlad: no fakes. Patched: DB upsert tested, upload live only. |
| 6 | spec review | Response shape undefined | medium | Patched with Vlad's list (popularity included). |
| 7 | spec review | `image_url` with an unset base URL | medium | Patched: required setting, service builds the URL. |
| 8 | spec review | `limit` bound from settings vs `Query(le=)` | medium | Patched: read when the router is built. |
| 9 | spec review | NEWEST order degenerate after seeding | medium | Patched: created_at by file position. |
| 10 | spec review | Seed semantics open; `delete` without caller | medium | Patched; `delete` dropped (Vlad: no deletes). |
| 11 | spec review | boto3 in the runtime image | low | Patched: dev group. |
| 12 | spec review | Region hard-coded in outputs | low | Patched: one local. |
| 13 | spec review | New required tfvars variable | low | Patched: tenancy derived; `media_writer_email` noted in Verification. |
| 14 | blind, verification-gap | Nothing stops runtime code importing boto3 via `app.infrastructure.storage` | medium | boto3 is dev-only; the image would crash on start. Patched: `protected` import contract. |
| 15 | verification-gap, blind | `upsert_by_slug` where clause (updated_at kept) untested | medium | Patched: T1/T2 test; insert now takes `updated_at` from the clock. |
| 16 | blind | No CHECK on popularity and calories | medium | Counter changed by a later story. Patched in unmerged 0006. |
| 17 | edge | `offset` above bigint answers 500 | low | asyncpg overflow. Patched: `le=2**63-1`. |
| 18 | blind | Seed script prints raw tracebacks, no summary | low | Patched: readable `MenuSeedFileError`, one summary line. |
| 19 | edge | `media_writer_email` without `{env}` collides across environments | low | Patched: validation block. |
| 20 | verification-gap | Committed seed folder not validated by a test | low | Vlad git-ignored `backend/seed/`. Rejected. |
| 21 | verification-gap, blind | Router limit bounds not tested with non-default settings | medium | Defaults are what ships. Defer. |
| 22 | blind | No Cache-Control; same key on replaced pictures | medium | Request quota and stale caches. Defer: decide with the quota question. |
| 23 | edge, blind | `MEDIA_PUBLIC_BASE_URL` of "/" or without scheme; `MENU_*` bounds unchecked | low | Operator misconfiguration, as in earlier stories. Rejected. |
| 24 | edge | total and page read in separate statements | low | Only a concurrent seed run differs. Rejected. |
| 25 | edge | Orphaned object when a picture changes extension; upload before upsert | low | No deletes by decision; rerun is safe. Rejected. |
| 26 | edge | Dish added later gets created_at near now | false | Intended: a new dish is the newest. |
| 27 | edge | Whitespace-only strings in the seed | low | Data under our control. Rejected. |
| 28 | edge | Tenancy taken from the compartment parent | low | Documented assumption in Verification. Rejected. |
| 29 | blind, edge, verification-gap | Pictures are JPEG, spec said WebP | low | Recorded in Spec Change Log. |
| 30 | blind | Region literal still in providers.tf and versions.tf | low | Backend block cannot use locals. Rejected. |
| 31 | blind | No 422 test for a non-UUID id | low | backend.md: no trivial validation cases. Rejected. |

## Design Notes

- Verified (oracle/terraform-provider-oci docs on GitHub): `access_type = "ObjectReadWithoutList"` allows anonymous GetObject and HeadObject only; Customer Secret Key `id` is the access key, `key` the secret. Oracle S3 docs: path-style endpoint `https://<namespace>.compat.objectstorage.<region>.oci.customer-oci.com`; SigV2 unsupported.
- Unverified: the native public object URL format used for `MEDIA_PUBLIC_BASE_URL`; confirm with `curl` after the first upload. Unverified: whether anonymous GETs count toward the 50,000 Always Free API requests a month.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports && uv run pytest` -- all pass.
- Throwaway `postgres:18` in tmpfs: `alembic upgrade head`, `downgrade 0005`, `upgrade head`, `alembic check` -- clean.
- `terraform validate` in `deploy/terraform` -- valid; `plan` and `apply` are Vlad's, after adding `media_writer_email` to `terraform.tfvars`. The tenancy comes from the parent of the project compartment (`oci_identity_compartment`), which assumes the compartment sits directly under the root.

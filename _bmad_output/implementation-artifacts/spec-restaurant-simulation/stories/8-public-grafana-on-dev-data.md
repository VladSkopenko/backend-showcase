---
title: 'Public Grafana on dev data'
type: 'feature'
created: '2026-11-16'
status: 'done'
baseline_commit: '59c8491495625818c0f3ef3f6e2b14ecc660925f'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/dashboards.md'
  - '{project-root}/deploy/platform/README.md'
  - '{project-root}/docs/adr/0007-single-vm-platform-and-app-stacks.md'
  - '{project-root}/docs/adr/0014-booking-simulator-on-dev.md'
  - '{project-root}/docs/adr/0015-platform-as-code.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The dev simulation produces bookings, pre-orders and staff decisions, but nobody outside the tailnet can look at them: there is no Grafana and no database role that is safe to hand to the public.

**Approach:** A dev-only PostgreSQL role that reads the restaurant data without emails, password hashes or tokens, of personal data only names, then Grafana in the platform stack, public through Caddy at `backend-showcase-grafana.duckdns.org` with anonymous Viewer, reading dev through that role (CAP-11). Dashboards are story 9.

## Boundaries & Constraints

**Always:**
- Two PRs. PR A `feature/grafana-db-role`: the role's password secret, migration `0021`, its tests, ADR 19. PR B `feature/public-grafana`: network, Grafana, Caddy, remaining secrets, docs.
- Role `grafana_reader`, created by migration `0021` only when `APP_ENVIRONMENT == "dev"` (the gate of `0011`); elsewhere upgrade and downgrade do nothing. A plain `CREATE ROLE`: a taken name fails loudly. Downgrade removes the role and its privileges.
- The role reads every current column of `bookings` (requests are its rows), `booking_participants`, `dining_tables`, `locations`, `dishes`; `preorder_items` without the free-text `note`; `users` only `id`, `first_name`, `last_name`. Nothing else: no `guests`, `booking_invites`, `refresh_tokens`, `verification_codes`, `user_oauth_accounts`, `notifications`, `alembic_version`. Every grant is a column list, never a whole table, so a new table or column is invisible until a migration grants it.
- First and last names of every dev user are public on purpose, real people who register on dev included: visitors may find themselves in the statistics. ADR 19 records it.
- An anonymous Viewer can send any SQL to the data source (Grafana docs; restricting it is Enterprise-only), so the role is the security boundary. Hard limits: the grants, `CONNECTION LIMIT 5`, `temp_file_limit`. Session defaults a viewer can lift with `SET`: `statement_timeout` 5 s, `default_transaction_read_only`.
- Accepted risk: PostgreSQL lets a role change its own password and reset its own session defaults, so one anonymous query can lock Grafana out of the database. Recovery is a new migration with a fresh verifier, like a bot password rotation. ADR 19 records it.
- Dev shares its data volume with prod, so the two verified ways the role could write to disk are closed on dev: the migration revokes `TEMPORARY` on the current database (`current_database()`, never a literal name) and `EXECUTE` on `lo_creat`, `lo_create`, `lo_from_bytea` from `PUBLIC`, and the downgrade grants them back. Any later non-owner role on dev loses them too. ADR 19 records that this does not close every conceivable path.
- The role logs in with a password stored as a SCRAM-SHA-256 verifier in the migration, as the bot hash in ADR 14. `deploy/platform/secrets.sh` generates the password, stores `GRAFANA_DB_PASSWORD` in the `platform` GitHub Environment and prints the verifier, computed by `postgres:18` itself with the password on stdin.
- Grafana reaches dev PostgreSQL over an internal network `analytics-<env>`, named from `APP_ENV` in the one app compose file. Every environment's PostgreSQL joins its own such network, as groundwork for analytics elsewhere later: staging and prod PostgreSQL are recreated once at promotion and sit on a network nobody else joins. Grafana joins `edge` (for Caddy) and, of the analytics networks, only `analytics-dev`.
- ADR 19 records that Grafana reads dev, not prod, and that every PostgreSQL gets an analytics network (both depart from AD-13; amends ADR 7), and the public query surface with its accepted risks.
- Grafana follows `deploy/platform/README.md` "Adding a service" and ADR 15: pinned `grafana/grafana:13.2.6`, `mem_limit`, healthcheck, data under `/srv/data/platform/grafana`, provisioning from `deploy/platform/grafana/`. The data source opens no more connections than the role's limit. Infra files are written one at a time with Vlad; every key and value is checked against official docs.

**Never:** A role or Grafana access on staging or prod; a new application setting or app secret for the role; dashboards (story 9); Prometheus, VictoriaLogs or Tempo data sources; an Enterprise feature; a Grafana login for anyone but the admin.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Dev upgrade | `APP_ENVIRONMENT=dev`, 0020 | `grafana_reader` exists with login, the verifier, limits and exactly the listed grants | N/A |
| Allowed read | role selects `id, first_name, last_name` from `users`, any column of `bookings` | rows | N/A |
| Personal data | role selects `email` or `*` from `users`, `note` from `preorder_items`, anything from `refresh_tokens` | no rows | permission denied |
| Write | role inserts into `dishes` | nothing written | permission denied |
| Disk write | role creates a temporary table or a large object | nothing created | permission denied |
| Other env | `local`, `staging`, `prod` | no role | N/A |
| Dev downgrade | `APP_ENVIRONMENT=dev`, 0021 | role and privileges gone, `PUBLIC` has `TEMPORARY` and the large-object functions back | N/A |
| Taken name | a role `grafana_reader` exists on dev | migration fails | DuplicateObject |
| Anonymous visitor | opens the public host without signing in | Grafana opens as Viewer | N/A |
| Anonymous query | Viewer posts `SELECT email FROM users` to the data source | no data | permission denied |

</frozen-after-approval>

## Code Map

- `backend/migrations/versions/0011_add_dev_booking_bots.py` -- the environment gate and a public hash constant; same shape for `0021`.
- `backend/migrations/versions/0021_add_grafana_reader_role.py` -- new; `op.execute` DDL, `down_revision = "0020"`.
- `backend/tests/support/migrations.py` -- `run_revision(connection, monkeypatch, file_name=, step=, environment=)` runs one revision inside the rolled-back test transaction; role DDL is transactional, so nothing leaks. Under `SET LOCAL ROLE` the role's own settings do not apply, so settings are asserted from the catalog, not by behaviour.
- `.github/workflows/ci.yml` -- the round trip runs as `local`, where `0021` does nothing; its dev branch is covered only by pytest under `dev` and by a throwaway database migrated as `dev`.
- `backend/tests/test_guest_bots_migration.py` -- the test shape for a gated migration.
- `deploy/platform/secrets.sh` -- `wanted`/`store`; the `caddy hash-password` block is the pattern for hashing over stdin.
- `deploy/app/compose.yml`, `deploy/app/deploy.sh`, `deploy/platform/deploy.sh` -- `edge` is the pattern for an external network created by the deploy scripts.
- `deploy/platform/compose.yml`, `deploy/platform/caddy/Caddyfile`, `.github/workflows/delivery.yml` (`deploy-platform`: `env` and `printf`) -- where a platform service and its secrets are added.
- `_bmad_output/implementation-artifacts/spec-platform-skeleton/services.md` -- Grafana's planned uid `472:0`, data path, `mem_limit` 256m, anonymous settings; re-check each against the docs.

## Tasks & Acceptance

**Execution (PR A):**
- [x] `deploy/platform/secrets.sh`, `deploy/platform/README.md` -- `GRAFANA_DB_PASSWORD` block that prints the verifier; secrets table row saying a re-run after the merge needs a new migration -- Vlad runs it; the verifier goes into `0021`.
- [x] `backend/tests/test_grafana_reader_migration.py` -- new; the matrix rows up to "Taken name": exact grant set from `information_schema`, role attributes, settings and verifier from the catalog, reads and denials under `SET LOCAL ROLE`, one denial per test -- contract.
- [x] `backend/migrations/versions/0021_add_grafana_reader_role.py` -- the migration -- role.
- [x] `docs/adr/0019-public-grafana-reads-dev.md`, `docs/adr/0007-single-vm-platform-and-app-stacks.md` (status line), `README.md` and `README.uk.md` (ADR table) -- the decision record -- docs.

**Execution (PR B, each file with Vlad):**
- [x] `deploy/app/compose.yml`, `deploy/app/deploy.sh`, `deploy/platform/deploy.sh` -- the `analytics-<env>` network.
- [x] `deploy/platform/compose.yml`, `deploy/platform/grafana/` -- Grafana service, init line, data source provisioning.
- [x] `deploy/platform/caddy/Caddyfile` -- the public host.
- [x] `deploy/platform/secrets.sh`, `.github/workflows/delivery.yml`, `deploy/platform/README.md` -- the admin password and both secrets in the deploy job.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass; CI's round trip and `alembic check` succeed.
- Given a throwaway PostgreSQL 18 with `APP_ENVIRONMENT=dev`, when it is migrated to head, down one revision and to head again, then each step succeeds and `grafana_reader` holds the committed verifier.
- Given both PRs deployed, when a browser outside the tailnet opens `https://backend-showcase-grafana.duckdns.org`, then Grafana shows without sign-in and the data source test passes: the first use of the real password, which only GitHub holds.
- Given both PRs deployed, when an anonymous request posts `SELECT email FROM users` to the data source query API, then PostgreSQL answers permission denied.

## Implementation Notes

- 2026-11-17, PR A: Vlad ran `deploy/platform/secrets.sh`; `GRAFANA_DB_PASSWORD` is stored in the `platform` environment and its verifier is committed in `0021`. `temp_file_limit` is 64 MB. `CREATE ROLE` runs through `exec_driver_sql`, because `op.execute` reads the `:` inside the verifier as bind parameters. The tests list the readable columns themselves and do not fail when a later migration adds a column: it simply stays invisible to the role.
- Verified: full suite (675 passed) and linters; a throwaway PostgreSQL 18 migrated as `dev` to head, down one, to head, down to base and to head again, `alembic check` clean; a real `grafana_reader` session there got its defaults (5 s, read-only, 64 MB), read names, bookings and dishes, and was denied `users.email`, `preorder_items.note`, `refresh_tokens`, a temporary table, a large object and an insert. The real password is not exercised until Grafana's data source connects in PR B.
- 2026-11-17, PR B: PR A merged as #40 and its dev deploy was green. The network is external and created by both deploy scripts as `--internal`, like `edge`, because compose accepts no attribute but `name` on an external network; dev PostgreSQL answers there as `app-dev-postgres`. Grafana gets `mem_limit` 768m, not the 256m planned in the platform skeleton: measured idle was about 285 MB in 14 processes (one backend per bundled data source plugin). Only `provisioning/datasources` is mounted, so the image's other provisioning directories stay. The data source pool is 4, one below the role's limit. The admin password is entered by Vlad and written to the `.env` in single quotes.
- Verified locally on throwaway containers (Grafana 13.2.6, PostgreSQL 18 migrated as `dev`, a test password): anonymous open, `/api/health` without a version, data source health, names readable, `users.email` and `refresh_tokens` denied, dashboard write 403; one anonymous request changed the role's password and the data source then failed, as ADR 19 accepts. Both compose files render with `docker compose config`; the Caddyfile validates in `caddy:2.11`; a single-quoted `.env` value keeps `$`, `#`, quotes and backslashes. Not exercised before the deploy: Caddy's certificate and proxying, the bind-mounted data directory, the real password.
- 2026-11-17, PR B after review: metrics endpoint off, plugin preinstall off, secure session cookie, short links blocked at Caddy, the admin password guard, and a data source report in `deploy/platform/deploy.sh`. Re-run on a throwaway stack with the real provisioning directory and the same Caddy directives: the report says `unreachable` before the role exists, `ok` with a working login and `unreachable` after the role is locked out; through Caddy `/` is 200, `/metrics` 404, `POST /api/short-urls` 403, names readable, `users.email` denied, admin login 200. Vlad stored `GRAFANA_ADMIN_PASSWORD` before the merge.
- 2026-11-17, live: PR B merged as #41; `Deploy platform` and `Deploy dev` green, the platform job reported `grafana data source: ok`. From outside the tailnet, without signing in: `https://backend-showcase-grafana.duckdns.org/` answers 200 with a Let's Encrypt certificate, plain HTTP redirects to it, `/api/health` shows no version, `/metrics` is 404, `POST /api/short-urls` 403, a dashboard write 403. The data source health is `Database Connection OK`, so the committed verifier matches the stored password. Anonymous queries through the data source read live data (893 confirmed, 397 cancelled and 16 rejected bookings, 5195 pre-order items, names) and are denied `users.email`, `users.password_hash`, `preorder_items.note`, `refresh_tokens` and an insert; the session runs as `grafana_reader` with the 5 s timeout, read-only default and 64 MB temp limit. The dev API answers `/health` after its PostgreSQL was recreated.

## Spec Change Log

## Review Triage Log

PR A, 2026-11-17. PostgreSQL claims were re-run by the parent session on a throwaway PostgreSQL 18.

| Finding | Verdict | Route |
|---|---|---|
| The committed verifier is never checked against the stored `GRAFANA_DB_PASSWORD` (verification-gap) | medium: only GitHub holds the password, so nothing before a real login can observe the pair | covered by this story's PR B: the data source test is the first real login (acceptance criterion 3) |
| A long query of the role holds a read lock, so a dev migration altering that table waits and API requests queue behind it (edge-case, blind) | medium: confirmed, `ALTER TABLE` behind the role's `pg_sleep` query hit `lock_timeout` | patch: ADR 19 consequence; defer: `lock_timeout` for migrations |
| `pg_logical_emit_message` writes WAL even in a read-only transaction (blind) | low: confirmed executable by the role; WAL is recycled at checkpoints, so it does not fill the volume | patch: named in ADR 19, not revoked |
| Plain `CREATE TABLE` and `CREATE SCHEMA` are not in the denied list (blind) | low: denied by PostgreSQL defaults, untested | patch: two test rows |
| Lifting the defaults is permanent through `ALTER ROLE`, and recovery must set them again (blind) | low: confirmed, the role ran `ALTER ROLE ... SET statement_timeout = 0` on itself | patch: ADR 19 wording |
| The revokes hold only in the application database; in `postgres` the role still creates temporary tables (blind) | low: true, unreachable through a data source bound to one database | patch: ADR 19 wording |
| ADR 19 quoted a sentence ADR 7 does not contain and did not name AD-13 (blind) | low: the sentence is AD-13's | patch: quote and status line |
| The role reads catalog metadata of hidden tables: names, row estimates, sizes (blind) | low: confirmed for `reltuples`; no values leak | patch: ADR 19 consequence |
| Dev downgrade fails when the role is absent, e.g. after a dump restored into a fresh cluster (edge-case) | low: real, but only on a database that lost a cluster-level object; ADR 19 records the restore case | rejected: a guard for a state no deploy produces |
| `LISTEN` plus repeated `NOTIFY` can grow the notification queue on the shared volume (edge-case) | maybe-false: not reproduced; would need a held transaction through Grafana's pool | rejected: low if true, ADR 19 already says not every path is closed |
| Denials run without savepoints, so later queries in the test would fail (edge-case, blind) | false: each denied statement is the last statement of its own parametrized test | rejected; the task line no longer says "savepoints" |
| The Intent says "without personal data" while names are public (edge-case) | low: wording inside the frozen block; the constraint below it states names are public on purpose | Vlad reworded the Intent on 2026-11-17: no emails, password hashes or tokens, of personal data only names |
| The story file is untracked and missing from the diff (blind) | false: left out of the review diff on purpose; it is committed with PR A | rejected |

PR B, 2026-11-17. Grafana and compose claims were re-run by the parent session on throwaway containers (Grafana 13.2.6 behind Caddy 2.11, PostgreSQL 18).

| Finding | Verdict | Route |
|---|---|---|
| `/metrics` is public through Caddy and shows the exact version (blind, edge-case) | medium: confirmed, 200 with `grafana_build_info`; against ADR 7 | patch: `GF_METRICS_ENABLED=false`, 404 after |
| Every start downloads unpinned app plugins from grafana.com (edge-case) | medium: confirmed, five app plugins and about 190 MB in the data directory | patch: `GF_PLUGINS_PREINSTALL_DISABLED=true`; bundled data sources stay, idle about 260 MB |
| An anonymous Viewer creates short links without limit (blind, edge-case) | medium: confirmed, each POST answers 200; links never expire; the volume is shared with prod | patch: Caddy answers 403 on `/api/short-urls*` |
| The admin session cookie has no `Secure` flag (blind) | low: confirmed in the defaults | patch: `GF_SECURITY_COOKIE_SECURE=true`; HSTS left to a later Caddy-wide decision |
| An admin password ending in a backslash breaks the `.env`; `${...}` in it is expanded by Grafana (edge-case) | medium: both confirmed (`config` fails to read the file; `pa${ss}wd` logs in as `pawd`) | patch: `secrets.sh` refuses `'`, `\` and `$` |
| Nothing automated observes the data source: the healthcheck passes without the database (verification-gap, blind) | medium: confirmed | patch: `deploy.sh` reports `grafana data source: ok` or `unreachable` after `up --wait`, without failing the deploy (the platform must deploy when dev is down, ADR 19). Vlad asked for the check; a container healthcheck was rejected because it would fail `up --wait` |
| The comment said containers on the internal network get no route outside (blind) | low: they have other networks | patch: comment |
| "Adding a service" knows only private UIs (blind) | low | patch: a line for public services |
| A later change to the provisioning file deploys green without taking effect (verification-gap, blind) | medium: by reading; compose does not notice a changed bind-mounted file and Grafana reads data sources at start | defer: story 9 adds dashboard provisioning and must settle reloads |
| No probe of the public route through Caddy (verification-gap) | low: same as the dev host | defer |
| No Docker log rotation; request paths are logged (blind) | medium: pre-existing for every container | defer |
| Both deploys may create `analytics-dev` at the same moment (blind, edge-case) | low: narrow window on the first rollout or a new VM; `edge` uses the same line | rejected |
| Setting `GRAFANA_ADMIN_PASSWORD` again changes nothing and no path recovers a forgotten one (blind) | low: the README says when it applies; Vlad keeps the password | rejected |
| No link to Grafana in the root README (blind) | false for this story: the page has no dashboards until story 9 | rejected; the link comes with story 9 |

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

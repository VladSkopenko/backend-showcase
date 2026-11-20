---
title: 'Prometheus reads dev Postgres'
type: 'feature'
created: '2026-11-20'
status: 'done'
baseline_commit: '06e721da0742ebc9525966fda95e55ab15143695'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-exporters/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-exporters/gotchas.md'
  - '{project-root}/docs/adr/0022-prometheus-scrapes-dev.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Prometheus sees the dev API and the VM, but not dev PostgreSQL: nobody sees its connections, size, transaction rate, cache hit ratio or locks.

**Approach:** A dev-only migration creates a plain LOGIN role `postgres_exporter` with a committed SCRAM verifier; postgres_exporter runs in the one app compose file, started by `deploy.sh` on dev only after the API, healthy only at `pg_up 1`, and Prometheus scrapes it as job `postgres` with `env: dev`. ADR 22 is amended; the roadmap item and the issue #26 Prometheus step are ticked.

## Boundaries & Constraints

**Always:** Migration `0026` gated on `environment == "dev"` like `0021`: `CREATE ROLE postgres_exporter LOGIN PASSWORD '<verifier>' CONNECTION LIMIT 5` (one idle connection plus one per concurrent scrape; over the limit a scrape silently loses every collector series), `statement_timeout = '5s'`, `default_transaction_read_only = on`; no grants, no `pg_monitor`; downgrade drops the role on dev only. Secret `POSTGRES_EXPORTER_PASSWORD` (hex, `openssl rand -hex 32`) in the GitHub Environment `dev`, set by Vlad before merge with a one-off script in the scratchpad (not committed) that copies the `GRAFANA_DB_PASSWORD` block of `deploy/platform/secrets.sh` with `--env dev` and prints the verifier. `delivery.yml` `deploy-dev` passes it over stdin like the other secrets. Service `postgres-exporter`: image `quay.io/prometheuscommunity/postgres-exporter:v0.21.1`, `restart: unless-stopped`; flags `--datasource.uri=postgres:5432/app?sslmode=disable` (the `DATA_SOURCE_URI` variable is deprecated in 0.21 and removed in 0.22), `--no-collector.wal`, `--no-collector.settings`, `--web.disable-exporter-metrics` (no `go_*`, `process_*`, `promhttp_*`; unlike node_exporter's, it also drops `postgres_exporter_build_info`); env `DATA_SOURCE_USER: postgres_exporter`, `DATA_SOURCE_PASS: ${POSTGRES_EXPORTER_PASSWORD:-}`; networks `default` and `observability` with alias `app-${APP_ENV}-postgres-exporter`; no `edge`, no published port; `mem_limit` from the dry run; healthcheck `["CMD-SHELL", "wget -qO- http://127.0.0.1:9187/metrics | grep -qx 'pg_up 1'"]`, every run a full scrape, interval 30s; `depends_on` postgres healthy. `deploy.sh` runs `up --detach --wait postgres-exporter` after the API only when `env` is `dev`. Prometheus job `postgres`, target `app-dev-postgres-exporter:9187`, label `env: dev`. ADR 22 amended 2026-11-20: the "API and host series only" bullet and the Consequences target list include job `postgres`; a Decision bullet for the exporter like node_exporter's (image, role without `pg_monitor`, collectors off, dev-only start, `pg_up` healthcheck); the data source keeps its name; accepted disclosures: `pg_static{version}`, database, role and table names, sizes, and that port 9187 answers without authentication on `observability`. Every key checked in the official docs with a link; one infrastructure file per step with Vlad after a local dry run.

**Never:** No `pg_monitor` or `pg_read_all_stats`, no `stat_statements`, no auto-discovered databases. No required `${...:?}` for the new variable. No dashboard (story 4), no query limit changes, no staging or prod (ADR 24). The API never depends on the exporter.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Scrape | dev deployed, secret set | target `postgres` up, `env="dev"`; `pg_up` 1; `pg_database_size_bytes{datname="app"}` queryable | N/A |
| Missing or wrong secret | empty password or verifier mismatch | `/metrics` still serves `pg_up 0`; healthcheck fails, `deploy.sh` exits non-zero after the API is up | dev job red, API untouched |
| Non-dev migration | `environment` local, staging or prod | no role created, downgrade a no-op | N/A |
| Role taken | role `postgres_exporter` exists | dev upgrade fails with "already exists" | migration rolls back |
| Hidden series | exporter `/metrics` | no `pg_settings_*`, `pg_stat_statements_*`, `pg_wal_*`, `go_*`, `process_*`, `promhttp_*`, `postgres_exporter_build_info` | N/A |

</frozen-after-approval>

## Code Map

- `backend/migrations/versions/0021_add_grafana_reader_role.py` -- pattern: `ROLE`, `VERIFIER`, dev gate via `get_settings`, `exec_driver_sql` for the verifier's `:`. Head is `0025`.
- `backend/tests/test_grafana_reader_migration.py` + `tests/support/migrations.py` (`run_revision`, `load_revision`) -- test pattern to mirror.
- `deploy/platform/secrets.sh:52-64` -- SCRAM verifier via `postgres:18 --single`; copy for the one-off script.
- `deploy/app/compose.yml:6-32` postgres (networks `default`, `analytics`), `:34-69` api (alias pattern), `:71-81` networks (`observability` external).
- `deploy/app/deploy.sh:31-38` -- postgres up, migrate, api up; the exporter step goes after `:36`.
- `.github/workflows/delivery.yml:128-153` -- `deploy-dev` env and `printf` to stdin.
- `deploy/platform/prometheus/prometheus.yml:16,25-28` -- header comment, job `node` shape.
- `deploy/platform/grafana/provisioning/datasources/prometheus.yaml:5-7`, `deploy/platform/compose.yml:166` -- comments naming what Prometheus holds.
- `backend/tests/test_grafana_dashboards.py:594-610` -- node collector test; add a postgres-exporter flag test next to it with a new path constant for `deploy/app/compose.yml` (only `PLATFORM` exists); match `--(no-)?collector\.` since `startswith("--collector.")` misses `--no-collector.*`.
- `docs/adr/0022-prometheus-scrapes-dev.md:5-13,48-56,113-130` -- Status, Decision bullets (`:48` "nothing else"), Consequences target list (`:114`) and disclosures.
- `docs/roadmap.md:108` -- "Postgres exporter for the dev database"; issue #26 body line 23 (Prometheus step).

## Tasks & Acceptance

**Execution:**
- [x] Local dry run (scratchpad, throwaway) -- `postgres:18` with a plain LOGIN role, the exporter with the planned flags on a throwaway network next to Prometheus: `promtool check config` passes, target up with `env="dev"`, `pg_up 1`, hidden families absent, healthcheck green and red with a wrong password, exit code of `up --wait` with an empty password recorded, series count and idle memory measured.
- [x] `backend/tests/test_postgres_exporter_migration.py` -- failing tests: dev role attributes and verifier, no memberships or grants, absent outside dev, dev downgrade removes it, taken name fails.
- [x] Vlad runs the one-off script -- secret in `dev`, verifier printed.
- [x] `backend/migrations/versions/0026_add_postgres_exporter_role.py` -- role per Always.
- [x] `backend/tests/test_grafana_dashboards.py` -- failing test pinning `--datasource.uri`, `--web.disable-exporter-metrics`, exactly `--no-collector.wal` and `--no-collector.settings` among `--(no-)?collector.*`, password `${POSTGRES_EXPORTER_PASSWORD:-}`, and job `postgres` with `env: dev`.
- [x] `deploy/app/compose.yml` -- `postgres-exporter` service.
- [x] `deploy/app/deploy.sh` -- dev-only start after the API.
- [x] `.github/workflows/delivery.yml` -- secret into `deploy-dev`.
- [x] `deploy/platform/prometheus/prometheus.yml` -- job `postgres`, header comment.
- [x] ~~`deploy/platform/grafana/provisioning/datasources/prometheus.yaml`, `deploy/platform/compose.yml` -- comments include dev Postgres.~~ Dropped by Vlad 2026-11-20: no comment-only edits.
- [x] `docs/adr/0022-prometheus-scrapes-dev.md` -- amendment per Always.
- [x] `docs/roadmap.md` -- tick line 108 (done; the issue #26 tick follows the live check after merge); issue #26 Prometheus step ticked after the live check, "(in progress)" and the staging/prod clause dropped (ADR 24).

**Acceptance Criteria:**
- Given the merge to main, when Delivery finishes, then deploy-dev and the platform job are green.
- Given the tailnet Prometheus, when targets are listed, then `postgres` is up with `env="dev"`, `pg_up` is 1 and `pg_database_size_bytes{datname="app"}` answers.
- Given the tailnet Prometheus, when `count({job="postgres",__name__=~"pg_settings_.*|pg_wal_.*|pg_stat_statements.*|go_.*|process_.*|promhttp_.*|postgres_exporter_build_info"})` and `min(pg_scrape_collector_success{job="postgres"})` are queried, then the first is empty and the second is 1.
- Given `docker compose config` with `APP_ENV=prod` and no `POSTGRES_EXPORTER_PASSWORD`, when run, then it passes.

## Implementation Notes

- Dry run 2026-11-20 (Docker Desktop, project `s3dry`, containers and networks removed): postgres:18 with role `postgres_exporter` (LOGIN, CONNECTION LIMIT 5, `statement_timeout` 5s, read-only), exporter v0.21.1 with the planned flags and env, Prometheus 3.15.1 on an internal network. `promtool check config` SUCCESS; target `postgres` up with `env="dev"`; `pg_up 1`; `pg_database_size_bytes{datname="app"}` present; 13/13 `pg_scrape_collector_success` 1; 36 `pg_locks_count`; zero `pg_settings_*`, `pg_wal_*`, `pg_stat_statements*`, `go_*`, `process_*`, `promhttp_*`, `postgres_exporter_build_info`; 248 data lines on an empty database. Healthcheck interval 30s, timeout 5s, retries 3, no start period: right password `up --wait` exit 0 after 32 s; empty password exit 1 ("application not healthy after 2m0s"). Idle memory 10.7 MiB, so `mem_limit: 32m`.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Evidence | Route |
|---|-------|---------|---------|----------|-------|
| 1 | spec review | `--disable-settings-metrics` does not exist in v0.21.1 | high | exporter exits: "unknown long flag"; CHANGELOG 0.20.0 | patch: `--no-collector.settings` |
| 2 | spec review | `DATA_SOURCE_URI` deprecated, removed in 0.22 | medium | README v0.21.1, startup WARN | patch: `--datasource.uri` |
| 3 | spec review | `CONNECTION LIMIT 3` leaves no spare; overflow hides series with `pg_up 1` | low | 5/15 degraded scrapes at 3 parallel | patch: limit 5, gotcha |
| 4 | spec review | ACs do not prove hidden series or the missing-secret failure | low | `config` accepted the broken flag | patch: AC and dry-run exit code |
| 5 | spec review | pipe healthcheck needs `CMD-SHELL` | low | busybox wget, grep present | patch |
| 6 | spec review | Code Map lines, test path constant, ADR 22 bullets | low | ADR 22 has 130 lines; node test at 594 | patch |
| 7 | re-review | `restart` missing from the service keys | medium | postgres, api, node-exporter all set `unless-stopped` | patch |
| 8 | re-review | SPEC.md says only wal off | low | SPEC.md:43 | patch |
| 9 | re-review | 44 `go_*`/`process_*`/`promhttp_*` series exposed | low | `--[no-]web.disable-exporter-metrics` in `--help` | patch: flag, as for node_exporter |
| 10 | narrow check | the flag also drops `postgres_exporter_build_info`, unlike node_exporter | medium | 1 line without the flag, 0 with it (verified) | patch: disclosure list, matrix, AC, gotchas |
| 11 | narrow check | series estimate and `promhttp_*` missing from matrix and AC | low | 201 data lines with the flag on an empty database | patch |
| 12 | code review: verification-gap | Nothing ties the compose alias to the Prometheus target | low | alias or network rename keeps every test and promtool green | patch: cross-file test |
| 13 | code review: verification-gap | `pg_up 1` healthcheck and `DATA_SOURCE_USER` unpinned | medium | a plain reachability check passes with `pg_up 0` | patch: test pins the healthcheck and the user against the migration's `ROLE` |
| 14 | code review: edge | Parallel scrapes over `CONNECTION LIMIT 5`; cap with `--web.max-requests` | low | only Prometheus and the healthcheck scrape (2 at most) | reject: unlikely, adds a flag |
| 15 | code review: edge | `--collection-timeout` 1m holds connections after a 5 s healthcheck timeout | false | role `statement_timeout` 5s ends every query | reject |
| 16 | code review: edge | ADR 22 says the exporter's own metrics are off | low | `pg_exporter_*`, `pg_scrape_collector_*`, `postgres_exporter_config_*` remain (verified) | patch: ADR names what is off |
| 17 | code review: blind | `pg_stat_activity_*` see only the exporter's session | low | verified: an open `app` transaction absent, `numbackends` 3 | patch: ADR 22 and gotchas say so; story 4 uses `numbackends` |
| 18 | code review: blind | "leaves the running API untouched" is wrong; start the exporter before the API | false | the API that just started keeps serving; order after the API is a settled decision | reject |
| 19 | code review: blind | no `start_period`: +30 s per deploy, unhealthy near the 120 s timeout | low | dry run: right password 32 s, empty password exit 1 at 120 s | reject: deploy still fails, adds keys |
| 20 | code review: blind | no compose test for ports, `edge`, alias | low | same gap as 12 | patch: test asserts no `ports`, `edge`, `analytics` |
| 21 | code review: blind | secret rollout and rotation undocumented | low | ADR 22 named the secret only | patch: ADR says set before merge, rotation needs a new migration |
| 22 | code review: blind | disclosure list misses `usename` and other labels | false | role names are listed; those labels only carry the exporter's own session | reject |

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_postgres_exporter_migration.py tests/test_grafana_dashboards.py` -- green (no other pytest running).
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests` -- clean.
- `docker compose --file deploy/app/compose.yml config --quiet` with dummy variables, with and without the new one -- no error.
- `promtool check config` on the changed `prometheus.yml` -- SUCCESS; `bash -n deploy/app/deploy.sh`; the edited `printf` line run locally with dummy values.

**Manual checks:**
- After merge: tailnet targets show `postgres` up; `up{job="postgres"}` has no gaps over the next day under `mem_limit`.

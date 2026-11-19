---
id: SPEC-gh-26-exporters
companions:
  - gotchas.md
  - ../spec-gh-26-api-metrics/gotchas.md
  - ../../../docs/adr/0022-prometheus-scrapes-dev.md
  - ../../../docs/adr/0009-alerting-from-outside-the-vm.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Server and dev database metrics, and the end of the observability phase

## Why

A vision to realize and a scope to close. Prometheus and the public Grafana show the dev API (issue #26, ADR 22), but not the VM every environment shares nor the dev database, although one data volume holds dev and prod data. Vlad decided on 2026-11-19 to finish Prometheus and Grafana with the exporters, add VictoriaLogs next, and stop the observability phase there; ADR 9, the spine and the roadmap still promise traces and Telegram alerts.

## Capabilities

- **CAP-1**
  - **intent:** Prometheus collects the VM's CPU, memory, load and disk, including free space on the shared `/srv/data` volume.
  - **success:** Prometheus over the tailnet shows target `node` up; free bytes of `/` and `/srv/data` are queryable.
- **CAP-2**
  - **intent:** Prometheus collects dev PostgreSQL's connections, database size, transaction rate, cache hit ratio and locks, labelled `env="dev"`.
  - **success:** Prometheus shows target `postgres` up with `env="dev"`; `pg_up` is 1 and the size of database `app` is queryable.
- **CAP-3**
  - **intent:** An anonymous visitor of the public Grafana sees the server's and the dev database's health on a dashboard next to `api`.
  - **success:** dashboard `server` shows host CPU, memory, load, free disk of `/` and `/srv/data`, and dev Postgres connections, size, transactions per second and cache hit ratio.
- **CAP-4**
  - **intent:** The decision record, the roadmap, the README and issue #26 say the observability phase ends after logs.
  - **success:** a new ADR supersedes ADR 9 (no Alertmanager, Telegram, healthchecks.io watchdog, Prometheus probe of n8n readiness, oldest-placed-order gauge or Tempo) and amends ADR 7, ADR 15's service list and every spine mention of Tempo, Alertmanager, Telegram, healthchecks.io and `redis_exporter`; the README's ADR table marks ADR 9 superseded and lists the new ADR; issue #26 has the Grafana and Prometheus steps ticked and the Tempo and Alertmanager steps marked dropped; `docs/roadmap.md` (Phase 4 list, including "Prometheus scraping all three environments and the exporters", Metrics row, stack rows, Done-when) and the README's "What is next" no longer promise traces, Telegram alerts or Redis exporters, and tie the staging and prod targets to their go-live in Phase 3, as ADR 22 already says.

## Constraints

- No Redis exists, so the exporters are node_exporter and postgres_exporter only.
- node_exporter runs in the platform stack on `observability` only and reads the host through a read-only root mount; no host network, so no network traffic metrics (Vlad, 2026-11-19).
- postgres_exporter runs on dev only, inside the app stack (AD-13): it joins its project's `default` network to reach `postgres` and `observability` with the alias `app-dev-postgres-exporter`. Staging and prod run none and need no new variable. Neither exporter joins `edge` or publishes a port.
- postgres_exporter logs in as role `postgres_exporter`, a plain LOGIN role without `pg_monitor`, created by a dev-only migration with a SCRAM verifier like `grafana_reader` (ADR 19). Its password is the secret `POSTGRES_EXPORTER_PASSWORD` in the GitHub Environment `dev`, a hex value (`.env` values are unquoted), stored by a script with `gh secret set` that prints the verifier computed like `GRAFANA_DB_PASSWORD`'s; it is set before the PR with the migration merges and reaches the server through `delivery.yml` (Vlad, 2026-11-19).
- The exporter service stays in the one app compose file (ADR 6) with `${POSTGRES_EXPORTER_PASSWORD:-}`: compose interpolates every service before filtering by profile or name, so a required variable would break staging and prod. `deploy/app/deploy.sh` starts it only when the environment is dev, after the API.
- The exporter's healthcheck requires `pg_up 1` in its own `/metrics`, so a missing secret or a wrong verifier turns the dev job red; the running API is untouched, and nothing in the app stack depends on the platform (AD-14).
- `env` comes from the scrape config (ADR 22); the node target carries none.
- Collectors are minimal: node_exporter with default collectors disabled and only `cpu`, `meminfo`, `loadavg`, `filesystem`, `diskstats`; postgres_exporter with the `wal` collector off and no statement statistics.
- The new ADR also amends AD-13 and ADR 7: postgres_exporter on dev only, node_exporter from the platform stack on `observability`, no `redis_exporter`.
- ADR 22 is amended: Prometheus holds API, host and dev Postgres series; the data source is renamed from "API metrics"; the disclosures accepted for anonymous Viewers are listed (exporter build info and the PostgreSQL version, database, role and table names, sizes, mountpoints).
- Images pinned by registry and tag, non-distroless for the `wget` healthcheck: `prom/node-exporter:v1.13.1`, `quay.io/prometheuscommunity/postgres-exporter:v0.21.1`.
- Platform service shape per issue #26: `mem_limit`, healthcheck, read-only config from the repository; new jobs go into `deploy/platform/prometheus/prometheus.yml`, reloaded by `deploy.sh`.
- Infrastructure files are written one per step with Vlad, every key checked in the official docs with a link, after a local dry run in throwaway containers.

## Non-goals

- Redis, cAdvisor or per-container metrics, host network traffic.
- Staging and prod API targets in this initiative; they come with those environments' go-live in Phase 3 (ADR 22).
- A staging or prod postgres_exporter (see Constraints).
- Alert rules, Alertmanager, Tempo and traces, the Prometheus probe of n8n readiness, the oldest-placed-order gauge (no orders in the final scope).
- Process collectors in the API.
- Postgres query statistics (`pg_stat_statements`).

## Success signal

- A visitor opens dashboard `server` on the public Grafana and sees the VM's free space on `/srv/data` and dev Postgres's transactions per second move with the bots' traffic, and the roadmap reads that observability ends with logs.

## Assumptions

- Dashboard `server` is one file in `deploy/platform/grafana/dashboards` with tag `restaurant`, like `api`, reading uid `prometheus`, with pinned data points and queries sized against the existing limits of ADR 22.

# Gotchas

Found by the independent spec review of 2026-11-19, checked against the repository and throwaway containers. Each one breaks a story if ignored.

## node_exporter (CAP-1)

- The local Docker Desktop is a VM: the host view (filesystems, `rslave` mount propagation) cannot be reproduced locally. Mount the root as `/:/host:ro` with `--path.rootfs=/host`; check `/` and `/srv/data` on the VM after the deploy.
- `--collector.disable-defaults` is required: `uname`, `os` and `dmi` are on by default. `node_exporter_build_info` with versions stays even with `--web.disable-exporter-metrics`; it is an accepted disclosure.
- Filesystem series include stray container mountpoints (`/etc/hostname`, `/etc/hosts`): panels select `mountpoint` `/` and `/srv/data` explicitly.
- `prom/node-exporter:v1.13.1` exists on Docker Hub; the GitHub release v1.13.0 has no image. Runs as `nobody`; busybox `wget` is present.

## postgres_exporter (CAP-2)

- A plain LOGIN role gives `pg_up 1` and every metric CAP-2 needs; only the `wal` collector fails (`permission denied for function pg_ls_waldir`), hence `--no-collector.wal`. Without `pg_read_all_stats` the `state` of other roles' sessions is hidden; `numbackends` is not.
- The role migration must create the role only on dev, under the same gate as `grafana_reader` (migration `0021`).
- Compose interpolates every service before filtering by profile or service name (verified on Compose 2.40.3: `up -d a`, `run`, `config` all fail on a missing `${X:?}` in another, profiled service). Hence `${POSTGRES_EXPORTER_PASSWORD:-}` and a dev-only start in `deploy.sh`.
- With an unreachable database or an empty password the exporter still serves `/metrics` with `pg_up 0`, so a plain `wget` healthcheck passes; check for the line `pg_up 1`.
- The secret travels through `delivery.yml` (`deploy-dev` job); `deploy/platform/secrets.sh` handles only the `platform` Environment.
- Defaults expose `pg_static{version}`, `postgres_exporter_build_info`, `pg_stat_activity_count{usename,...}`, `pg_roles_connection_limit{rolname}` and per-table statistics; no query text unless `stat_statements` is enabled.
- `quay.io/prometheuscommunity/postgres-exporter:v0.21.1`, runs as `nobody`; `*-distroless` tags have no shell or `wget`.

## Prometheus and Grafana (CAP-3)

- About 935 node series with the minimal collectors and about 580 postgres series (284 of them `pg_settings_*`) fit the current query limits.
- `backend/tests/test_grafana_dashboards.py` asserts the directory holds the five SQL dashboards plus `api`: it must allow `server`.
- Node series carry no `env`, so an `env` variable cannot filter node panels.
- A dashboard with about nine panels exceeds `--query.max-concurrency=4` and queues, as ADR 22 already records for `api`.
- `deploy/platform/prometheus/prometheus.yml` and ADR 22 say "API counters only"; both change with the amendment.

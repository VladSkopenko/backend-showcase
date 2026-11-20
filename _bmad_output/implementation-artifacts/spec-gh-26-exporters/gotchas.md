# Gotchas

Found by the independent spec review of 2026-11-19, checked against the repository and throwaway containers. Each one breaks a story if ignored.

## node_exporter (CAP-1)

- The local Docker Desktop is a VM: the host view (filesystems, `rslave` mount propagation) cannot be reproduced locally. The repository mounts `/:/host:ro,rslave` with `--path.rootfs=/host` (Ubuntu's `/` is shared on the VM); the local dry run mounts `/:/host:ro`, because `rslave` fails on Docker Desktop. Check `/` and `/srv/data` on the VM after the deploy; locally `/` is overlay and excluded.
- diskstats logs `Failed to open directory, disabling udev device properties` (`/run/udev/data`) on every start. Harmless, and it keeps disk model and serial out of `node_disk_info`: do not add `--path.udev.data`.
- Renaming the provisioned data source with the same uid crash-loops Grafana on its next start unless `deleteDatasources` removes the old name; provisioning is read only at start. The name stays.
- `--collector.disable-defaults` is required: `uname`, `os` and `dmi` are on by default. `node_exporter_build_info` with versions stays even with `--web.disable-exporter-metrics`; it is an accepted disclosure.
- Filesystem series include container mountpoints (`/etc/hostname`, `/etc/hosts`, `/etc/resolv.conf`) and host tmpfs such as `/run`: panels select `mountpoint` `/` and `/srv/data` explicitly.
- `prom/node-exporter:v1.13.1` exists on Docker Hub; the GitHub release v1.13.0 has no image. Runs as `nobody`; busybox `wget` is present.

## postgres_exporter (CAP-2)

- A plain LOGIN role gives `pg_up 1` and every metric CAP-2 needs; only the `wal` collector fails (`permission denied for function pg_ls_waldir`), hence `--no-collector.wal`. Without `pg_read_all_stats` the `state` of other roles' sessions is hidden; `numbackends` is not. In practice `pg_stat_activity_count` and `pg_stat_activity_max_tx_duration` show only the exporter's own session (verified 2026-11-20: an open `app` transaction was absent while `numbackends` counted it), so the dashboard counts connections with `pg_stat_database_numbackends` and shows no transaction age.
- The role migration must create the role only on dev, under the same gate as `grafana_reader` (migration `0021`).
- Compose interpolates every service before filtering by profile or service name (verified on Compose 2.40.3: `up -d a`, `run`, `config` all fail on a missing `${X:?}` in another, profiled service). Hence `${POSTGRES_EXPORTER_PASSWORD:-}` and a dev-only start in `deploy.sh`.
- With an unreachable database or an empty password the exporter still serves `/metrics` with `pg_up 0`, so a plain `wget` healthcheck passes; check for the line `pg_up 1`.
- The secret travels through `delivery.yml` (`deploy-dev` job); `deploy/platform/secrets.sh` handles only the `platform` Environment.
- Defaults expose `pg_static{version}`, `postgres_exporter_build_info` (dropped by `--web.disable-exporter-metrics` together with `go_*`, `process_*`, `promhttp_*`, unlike node_exporter's build info), `pg_stat_activity_count{usename,...}`, `pg_roles_connection_limit{rolname}` and per-table statistics; no query text unless `stat_statements` is enabled.
- `quay.io/prometheuscommunity/postgres-exporter:v0.21.1`, runs as `nobody`; `*-distroless` tags have no shell or `wget`. Busybox `wget` and `grep` are present, so the pipe healthcheck needs `CMD-SHELL`.
- `--disable-settings-metrics` was removed in 0.20.0 and the exporter exits on it; `--no-collector.settings` replaces it (verified 2026-11-20). `DATA_SOURCE_URI` is deprecated in 0.21 and removed in 0.22: use `--datasource.uri`; `DATA_SOURCE_USER` and `DATA_SOURCE_PASS` stay environment variables.
- The exporter keeps one idle connection and opens one more per concurrent scrape; over the role's connection limit a scrape logs `too many connections` but still reports `pg_up 1` with every collector series missing. Every healthcheck run is a full scrape.

## Prometheus and Grafana (CAP-3)

- About 935 node series with the minimal collectors and about 200 postgres series (on an empty database) with the settings and wal collectors and the exporter's own metrics off fit the current query limits.
- `backend/tests/test_grafana_dashboards.py` asserts the directory holds the five SQL dashboards plus `api`: it must allow `server`.
- Node series carry no `env`, so an `env` variable cannot filter node panels.
- A dashboard with about nine panels exceeds `--query.max-concurrency=4` and queues, as ADR 22 already records for `api`.
- `deploy/platform/prometheus/prometheus.yml` and ADR 22 say "API counters only"; both change with the amendment.

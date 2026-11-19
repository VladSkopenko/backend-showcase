---
title: 'Prometheus reads the host'
type: 'feature'
created: '2026-11-19'
status: 'done'
baseline_commit: '61f1414'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-exporters/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-exporters/gotchas.md'
  - '{project-root}/docs/adr/0022-prometheus-scrapes-dev.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Prometheus scrapes only the dev API, so nobody sees the VM's CPU, memory, load or the free space on `/srv/data`, the one volume that holds dev and prod data.

**Approach:** Run node_exporter in the platform stack on `observability`, with the host root mounted read-only and only the collectors CAP-1 needs, and scrape it as job `node`. Amend ADR 22 for the new series and fix the stale ADR 9 reference in the platform compose. The data source keeps its name.

## Boundaries & Constraints

**Always:** Image `prom/node-exporter:v1.13.1`. Flags: `--path.rootfs=/host`, `--collector.disable-defaults` with only `cpu`, `meminfo`, `loadavg`, `filesystem`, `diskstats`, and `--web.disable-exporter-metrics`. Volume `/:/host:ro,rslave`. Network `observability` only, reached by service name; no `edge`, no published port, no host network or pid namespace (Vlad, 2026-11-19). `mem_limit` from the dry run, healthcheck `wget` on `http://127.0.0.1:9100/` (the landing page, which runs no collectors), no data directory and so no `init` line; the comment above `init` says a service with a data directory adds a line. Prometheus job `node`, target `node-exporter:9100`, no `env` label (one host), reloaded by `deploy.sh`. ADR 22 is amended: Prometheus holds API and host series; the data source keeps its name "API metrics (Prometheus)", because renaming a provisioned source with the same uid crash-loops Grafana without a restart that `deploy.sh` does not do, and only its comments change; accepted disclosures: `node_exporter_build_info` with versions, host and container mountpoints, filesystem types and disk device names; node-exporter:9100 answers without authentication to every container on `observability`; the "API counters only" wording in ADR 22, `prometheus.yml` and the data source comment changes with it. The n8n healthcheck comment in `deploy/platform/compose.yml` cites ADR 23 instead of ADR 9. Infrastructure files are written with Vlad one file per step, every key checked in the official docs with a link, after a local dry run in throwaway containers.

**Never:** No network traffic collector (`netdev`), no `uname`, `os`, `dmi`, `systemd` or process collectors. No Postgres exporter (story 3), no dashboard (story 4), no change to the query limits. No staging or prod change.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Scrape | platform deployed on the VM | target `node` up; `node_filesystem_avail_bytes{mountpoint="/"}` and `{mountpoint="/srv/data"}` queryable | N/A |
| Host-wide values | busy VM | `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`, `node_load1` describe the VM, not the container | N/A |
| Hidden collectors | `/metrics` of node_exporter | no `node_uname_info`, `node_os_info`, `node_network_*`, `go_*` | N/A |
| Exporter down | node_exporter stopped | target `node` down; API scraping and Grafana unaffected | none |

</frozen-after-approval>

## Code Map

- `deploy/platform/compose.yml:104` -- n8n healthcheck comment "(ADR 9)"; `:167-205` prometheus service (shape to copy: pinned image, `mem_limit`, healthcheck, networks); `:207-215` networks with `observability` external.
- `deploy/platform/prometheus/prometheus.yml:15-23` -- one job `api` with the "API counters only" comment; new job `node` next to it.
- `deploy/platform/grafana/provisioning/datasources/prometheus.yaml:5-7` -- data source name "API metrics (Prometheus)" (stays) and its "API counters only" comment.
- `docs/adr/0022-prometheus-scrapes-dev.md` -- "API counters only" decision bullet, Status line with the 2026-11-19 amendment pattern.
- `backend/tests/test_grafana_dashboards.py` -- data source test checks uid, type, access, url, isDefault, editable, timeInterval, not the name; stays green.
- Gotchas (companion): local Docker Desktop is a VM, so `/srv/data` and `rslave` are checked on the server; `node_exporter_build_info` stays even with `--web.disable-exporter-metrics`.

## Tasks & Acceptance

**Execution:**
- [x] Local dry run (scratchpad, throwaway) -- node_exporter with the planned flags and `/:/host:ro` (`rslave` fails on Docker Desktop and is confirmed on the VM) next to Prometheus on a throwaway internal network: `promtool check config` passes, target `node` up, `/metrics` holds `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`, `node_load1`, `node_filesystem_avail_bytes`, `node_disk_*` and none of the hidden families, series count and idle memory measured.
- [x] `deploy/platform/compose.yml` -- `node-exporter` service per Always; the n8n comment cites ADR 23; the `init` comment scoped to services with a data directory; the prometheus service comment names the host as well as the dev API.
- [x] `deploy/platform/prometheus/prometheus.yml` -- job `node`; the header comment no longer says API counters only.
- [x] `deploy/platform/grafana/provisioning/datasources/prometheus.yaml` -- comment: API and host series; name unchanged.
- [x] `docs/adr/0022-prometheus-scrapes-dev.md` -- amended 2026-11-19 for host series, the unchanged data source name, the accepted disclosures and who can reach the exporter.

**Acceptance Criteria:**
- Given the merge to main, when Delivery finishes, then the platform job is green and its summary reads `platform deployed, prometheus reloaded, ...`.
- Given the Prometheus UI over the tailnet, when `node_filesystem_avail_bytes{mountpoint=~"/|/srv/data"}` is queried, then both mountpoints return a value.
- Given the public Grafana after the deploy, when `/api/datasources` is read anonymously, then it still shows "API metrics (Prometheus)" with uid `prometheus` and Grafana did not restart.

## Implementation Notes

- Dry run 2026-11-19 (Docker Desktop 29.1.3, project `s2dry`, torn down): node_exporter v1.13.1 with the planned flags and `/:/host:ro` next to Prometheus 3.15.1 on an internal network; `promtool check config` SUCCESS with job `node`; target `node` up; 751 series; `node_load1`, `node_memory_MemAvailable_bytes`, 80 `node_cpu_seconds_total`, `node_filesystem_avail_bytes` (29 Docker Desktop mountpoints, none of them `/` since the local root is overlay), 324 `node_disk_*`; zero `node_uname*`, `node_os*`, `node_network*`, `go_*`, `process_*`, `promhttp_*`; `node_exporter_build_info` present; idle 8 MiB, so `mem_limit: 32m`.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Evidence | Route |
|---|-------|---------|---------|----------|-------|
| 1 | spec review | Renaming the data source with the same uid crash-loops Grafana on its next start | high | Reproduced on 13.2.6: "data source with the same uid already exists" | rename dropped |
| 2 | spec review | Provisioning is read only at start; deploy.sh never restarts Grafana | high | Running Grafana kept the old name | rename dropped |
| 3 | spec review | Dry run with `rslave` fails on Docker Desktop; story and gotchas disagree | medium | "not a shared or slave mount" | patch: `/:/host:ro` locally, `rslave` on the VM |
| 4 | spec review | `/` is VM-only; container and `/run` mountpoints exposed | low | overlay excluded locally | patch: disclosure widened, VM-only check |
| 5 | spec review | Healthcheck path unnamed | low | `/` and `/metrics` both 200 | patch: `/` |
| 6 | spec review | `init` comment says every new service adds a line | low | compose.yml:3-4 | patch |
| 7 | spec review | ADR 22 amendment omits who can reach the exporter | low | ADR 22 Consequences | patch |
| 8 | spec review | udev error on start | info | harmless, hides disk serials | gotcha |
| 9 | re-review | Prometheus service comment says it scrapes only the dev API | low | compose.yml:165 | patch |
| 10 | code review: verification-gap | Collector restriction (the ADR 22 disclosure boundary) has no automated check | medium | No test reads the node-exporter block; healthcheck on `/` runs no collectors | patch: test pins the collector set |
| 11 | code review: verification-gap | Nothing ties job `node` to the compose service and network | low | promtool does not resolve targets | reject: manual tailnet check after merge |
| 12 | code review: verification-gap | Platform README says every service needs init and a data directory | low | README:30-34 | patch |
| 13 | code review: edge | An unhealthy node-exporter fails `up --wait` and skips the reload steps | low | Same contract as every platform service | reject |
| 14 | code review: edge | Container bind mounts appear as extra mountpoints | low | Panels select `/` and `/srv/data` explicitly (story 4); recorded in gotchas | reject |
| 15 | code review: blind | SPEC still requires the rename; story 2 file missing; rslave vs gotchas | false | Reviewer read origin/main; the worktree's SPEC, story file and gotchas are updated | reject |
| 16 | code review: blind | ADR 22 Decision bullet 1 still says one job `api` | medium | ADR 22:29-31 | patch |
| 17 | code review: blind | ADR 22 Consequences' target list omits `node-exporter:9100` | low | ADR 22:113 | patch |
| 18 | code review: blind | ADR 22 Status and the compose comment attribute the amendment to ADR 23 | low | ADR 23 does not amend ADR 22 | patch: "following ADR 23", comment cites ADR 22 and 23 |
| 19 | code review: blind | n8n comment cites ADR 23 for readiness semantics | low | ADR 23 only keeps the healthcheck | patch |
| 20 | code review: blind | `mem_limit` from an idle local measurement | low | measured while scraped every 15 s, but on Docker Desktop | patch: comment, `up{job="node"}` without gaps on the VM |

## Verification

**Commands:**
- `docker compose --file deploy/platform/compose.yml config --quiet` with dummy variables -- expected: no error.
- `promtool check config` on the changed `prometheus.yml` -- expected: SUCCESS.
- `cd backend && uv run pytest tests/test_grafana_dashboards.py` -- expected: green.

**Manual checks:**
- After merge: tailnet `:9090/targets` shows `node` up; `node_filesystem_avail_bytes` for `/` (ext4) and `/srv/data` answers (VM-only check); `node_uname_info` absent; over the following day `up{job="node"}` has no gaps, so `mem_limit: 32m` does not OOM-kill the exporter under real scrapes (nobody can run `docker stats` on the VM, ADR 2).

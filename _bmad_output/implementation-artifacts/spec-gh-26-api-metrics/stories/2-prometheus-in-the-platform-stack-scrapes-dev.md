---
title: 'Prometheus in the platform stack scrapes dev'
type: 'feature'
created: '2026-11-19'
status: 'done'
baseline_commit: '2d066784841a3564124c5034c634708fd6a2c526'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-api-metrics/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-api-metrics/gotchas.md'
  - '{project-root}/deploy/platform/README.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The dev API serves request metrics on port 9000 (story 1), but nothing collects them, so story 3's Grafana dashboard has no data source.

**Approach:** Add Prometheus 3.15 to the platform stack, scraping `app-dev-api:9000` every 15 s over a new internal network `observability` with the label `env="dev"`, its UI only on the tailnet at port 9090. ADR 22 records the setup and that Caddy, not the network, is the metrics port's boundary (amends the spine's Metrics convention).

## Boundaries & Constraints

**Always:** Image `prom/prometheus:v3.15.1`, which runs as `nobody` 65534:65534 (checked 2026-11-19). One scrape job `api`, target `app-dev-api:9000`, `env: dev` set in the scrape config. Prometheus is on `networks: [default, observability]`. The API joins `observability` with alias `app-<env>-api` in the one app compose file, so every environment's API joins it. Both deploy scripts create `observability` as `--internal` if missing. The platform deploy validates the config with `promtool` in a throwaway container before `up`, and after `up` sends SIGHUP, because compose does not recreate a container for a changed bind-mounted file. The service follows `deploy/platform/README.md` "Adding a service": pinned image, `mem_limit`, healthcheck, `depends_on` init, data in `/srv/data/platform/prometheus`, config directory `deploy/platform/prometheus/` mounted read-only. `command:` repeats `--config.file` and `--storage.tsdb.path`. Each infrastructure file is written with Vlad one file per step, every key checked in the official docs with a link, after a local dry run in throwaway containers.

**Never:** No `--web.enable-lifecycle`. No self-scrape and no job other than `api`. No staging or prod targets, no exporters, no alerting. No Caddy site, no `edge` network for Prometheus, no published host port. No Grafana data source or query limits (story 3). No new secrets. No `depends_on` from the app stack on the platform (AD-14). No application code change.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Scrape | dev API up | target `api` up with `env="dev"`, `instance="app-dev-api:9000"`; `http_requests_total{env="dev"}` queryable | N/A |
| Dev down | platform deployed, dev not yet or stopped | platform deploy succeeds; target `api` down | none: AD-14 |
| Platform down | dev deploy with no Prometheus | dev deploys and serves | none |
| Config changed | push to main edits `prometheus.yml` | deploy validates and reloads, new config active without restart | invalid config fails the deploy before `up`; the running Prometheus and the rest of the stack are untouched |
| Tailnet UI | admin device opens `https://<PLATFORM_HOST>:9090` | Prometheus UI with a `*.ts.net` certificate | N/A |
| Public | any public host, `/metrics` on the dev host | no Prometheus; dev `/metrics` 404 | N/A |

</frozen-after-approval>

## Code Map

- `deploy/platform/compose.yml` -- `init` command holds one `install -d` line per service; add `/data/prometheus` as `65534:65534`, mode 700. `tailscale` reaches UIs by service name on the project `default` network: listing networks on Prometheus must name `default`. `backend/tests/test_grafana_dashboards.py:255-261` regex-matches exactly one `GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH:` line and exactly one `- ./grafana/dashboards:` mount; the Prometheus mount does not match it. The image declares `VOLUME /prometheus`; the bind mount must land exactly there.
- `deploy/platform/deploy.sh` -- creates `edge` and `analytics-dev`, runs `up --wait`, then reloads Caddy, then prints one final line. Its whole stdout becomes the job's step summary (`.github/workflows/delivery.yml:193-198`), so promtool's success output goes to `/dev/null` (failures print to stderr, exit 1). A recreated container (first deploy, image bump, story 3's `command` change) with a bad config would exit and fail `up --wait`, hence the check runs before `up`.
- `deploy/platform/tailscale/serve.json` -- one TCP/Web pair per UI (n8n 5678); add 9090 → `http://prometheus:9090`. The tailnet policy grant already covers tcp 9090 (platform-skeleton rollout, done by Vlad).
- `deploy/app/compose.yml` -- `api` networks: `default` and `edge` with alias; add `observability` with the same alias and declare it `external: true` (compose rejects `internal` on an external network, comment pattern as `analytics`).
- `deploy/app/deploy.sh` -- creates `edge` and `analytics-$env`; add `observability` the same way.
- `.github/workflows/delivery.yml` -- `deploy-platform` runs on every push to main with no path filter; unchanged.
- `deploy/platform/caddy/Caddyfile` -- proxies only `app-dev-api:8000` and Grafana; unchanged.
- `docs/adr/` -- highest number is 0021 (decisions by email only), so this ADR is 0022; ADR 7's Status line lists its amendments. ADR 19 amends the spine through the ADR without editing the spine; same here.

## Tasks & Acceptance

**Execution:**
- [x] Local dry run (scratchpad, throwaway) -- internal `observability` network, a stand-in on alias `app-dev-api` serving `/metrics` on 9000, Prometheus with the draft config: `promtool check config` passes, `/-/ready` is 200, `/api/v1/targets` shows `api` up with `env="dev"`, edited config is active after SIGHUP, idle memory measured for `mem_limit` -- proves every infra file before Vlad writes it.
- [x] `deploy/app/deploy.sh` -- create `observability` as `--internal` if missing -- the API's network must exist before compose up.
- [x] `deploy/app/compose.yml` -- `api` joins external `observability` with alias `app-<env>-api` -- Prometheus resolves the target by alias.
- [x] `deploy/platform/prometheus/prometheus.yml` -- `global.scrape_interval: 15s`, job `api`, static target `app-dev-api:9000`, label `env: dev` -- CAP-2.
- [x] `deploy/platform/compose.yml` -- init line; `prometheus` service: image, `restart: unless-stopped`, `mem_limit` from the dry run, `command` with `--config.file=/etc/prometheus/prometheus.yml`, `--storage.tsdb.path=/prometheus` (retention lives in `prometheus.yml`, see Spec Change Log); volumes `./prometheus:/etc/prometheus:ro` and `/srv/data/platform/prometheus:/prometheus`; healthcheck `wget` on `http://127.0.0.1:9090/-/ready`; `depends_on` init; networks `default`, `observability`; `observability` declared external.
- [x] `deploy/platform/deploy.sh` -- create `observability` `--internal`; before `up`, `run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml > /dev/null`; after the Caddy reload, `kill -s SIGHUP prometheus`; the final line becomes `platform deployed, prometheus reloaded, grafana data source: $datasource`.
- [x] `deploy/platform/tailscale/serve.json` -- 9090 HTTPS → `http://prometheus:9090`.
- [x] `docs/adr/0022-prometheus-scrapes-dev.md` -- Prometheus in the platform stack scrapes dev only, `env` from the scrape config, one `observability` network for all environments' APIs, UI on the tailnet, config reload by promtool and SIGHUP with lifecycle off, holds API counters only, retention bound; metrics port reachable over `edge` too, so Caddy is the boundary, amending the spine's Metrics convention ("reachable only over `observability`").
- [x] `docs/adr/0007-single-vm-platform-and-app-stacks.md` -- Status: amended by ADR 22.
- [x] `README.md`, `README.uk.md` -- Platform row: Prometheus scrapes the dev API, UI only on the tailnet (ADR 22); ADR index row 22.
- [x] `spec-gh-26-api-metrics/SPEC.md`, `stories.yaml` -- "ADR 21" becomes "ADR 22" (`SPEC.md:32,37`, `stories.yaml:12`).

**Acceptance Criteria:**
- Given the merge to main, when Delivery finishes, then both deploy jobs are green and the platform job summary reads `platform deployed, prometheus reloaded, ...`.
- Given the dev API on the internal `observability` network, when it calls out (an assistant request on dev), then outbound traffic still works.
- Given an admin device on the tailnet, when `https://<PLATFORM_HOST>:9090/targets` opens, then `api` is up with `env="dev"`.
- Given the public internet, when the dev host and the Grafana host are probed, then neither serves Prometheus, and dev `/metrics` is 404.

## Implementation Notes

- Dry run 2026-11-19 (Docker Desktop 29.1.3, Compose 2.40.3, arm64; compose project `dryrun-prom`, external network `dryrun-observability --internal`, torn down): init `install -d -o 65534 -g 65534 -m 700` gives `/prometheus` owned 65534:65534 inside the container; `up --wait` healthy via `wget /-/ready`; target `api` up, labels `{env="dev",instance="app-dev-api:9000",job="api"}`, series carry `env="dev"`; runtime retention `15d or 1GiB`; flag `web.enable-lifecycle=false`; a container on `default` only cannot reach `app-dev-api:9000`; idle 43 MiB, so `mem_limit: 256m`. `compose kill -s SIGHUP` applied an edited `scrape_interval` without a restart; a broken file fails `compose run --rm --no-deps --entrypoint promtool ...` with exit 1 and `FAILED: ...` on stderr; SIGHUP with a broken file keeps the old config. `kill` and the promtool check print nothing on stdout.
- Prometheus 3 refuses a target without a `Content-Type` (`Failed to determine correct type of scrape target`); a busybox `httpd` stand-in hits this, prometheus-client sends `text/plain; version=0.0.4`. The stand-in used `nc` with that header.
- First platform deploy: `compose run` of the promtool check mounts `/srv/data/platform/prometheus` before init has run, so Docker creates it as root; init's `install -d` then re-applies 65534:65534 and 700 before Prometheus starts.
- Outbound check 2026-11-19 (review VG1, Docker 29.1.3): a busybox container on a normal network plus an `--internal` one, joined in either order, reached `https://example.com`; the default route stays on the normal network (`default via 172.18.0.1 dev eth1`). Post-merge AC with an assistant request on dev still applies (the VM's Docker version was not checked).

## Spec Change Log

- 2026-11-19, while writing `compose.yml`: the 3.15 command-line reference marks `--storage.tsdb.retention.time` and `--storage.tsdb.retention.size` `[DEPRECATED]` in favour of `storage.tsdb.retention.time`/`size` in the config file, which take precedence and reload on SIGHUP. Retention (15d, 1GB) moved to `prometheus.yml`; `command` keeps only the two paths. Checked in a throwaway container: runtime retention `15d or 1GiB`, log `TSDB retention updated duration=15d size=1GiB`. KEEP: both limits set explicitly.

## Review Triage Log

| # | Layer | Finding | Verdict | Evidence | Route |
|---|-------|---------|---------|----------|-------|
| 1 | spec review | `retention.size` alone disables the 15d time retention | high | Throwaway run: `storageRetention: "1GiB"` | patch: add `retention.time=15d` |
| 2 | spec review | promtool after `up` misses the recreate case | medium | `deploy.sh:17-19`; a recreated container with bad config exits | patch: check before `up` |
| 3 | spec review | promtool stdout pollutes the step summary; nothing prints the reload | low | `delivery.yml:193-198` writes stdout to the summary | patch |
| 4 | spec review | ADR number fix has no task; gotchas.md has no mention | low | grep: `SPEC.md:32,37`, `stories.yaml:12` | patch |
| 5 | spec review | README ADR index row missing | low | `README.md:104-108` lists every ADR | patch |
| 6 | spec review | Code Map misdescribes what the dashboard test reads | low | test regexes two lines only | patch |
| 7 | spec review | No check of the API's outbound traffic on an internal network | low | only postgres sits on an internal network today | patch: AC |
| 8 | spec review | Both deploys may race creating `observability` | low | same existing pattern as `analytics-dev`; deploy-dev waits for the image build | reject |
| 9 | verification-gap | API outbound traffic on an internal network unchecked before merge | low | Filed gap; closed by a local check: outbound works in both join orders, default route via the normal network | patch: Implementation Notes |
| 10 | verification-gap, edge, blind | Final line says "prometheus reloaded" without confirming the reload | low | True that nothing reads the reload result; but promtool validates the same config loader first, and a reload of a promtool-valid file failing was not shown reachable; a status probe adds a branch, rewording edits the spec's AC | reject |
| 11 | edge | Parallel deploys race creating `observability` | low | carried #8: deploy-dev waits for the image build, platform starts at once; same pattern as `edge` and `analytics-dev` | reject |
| 12 | edge | A pre-existing non-internal `observability` network would be reused | false | Nothing on the VM creates that name; the server is built by Terraform and cloud-init only (ADR 8); state not shown reachable | reject |
| 13 | edge | "UI on the tailnet only" overstates: containers on `observability` and `default` reach `prometheus:9090` unauthenticated | low | Compose gives the service name on every network it joins; ADR 22 claimed tailnet-only without that caveat | patch: ADR 22 Consequences |
| 14 | blind | ADR 22 omits the lowered query limits that SPEC.md says it records | low | Story 3 adds the limits and amends ADR 22 (`stories.yaml` story 3); not this story's decision | reject |
| 15 | blind | `deploy/app/deploy.sh` comment says Prometheus scrapes each environment; only dev is scraped | low | Comment wording vs ADR 22 "without being scraped"; the platform deploy.sh comment ("way to each environment's API") is accurate | patch |
| 16 | blind | `observability` comment in app compose reads as one network per environment | low | Sits under `analytics`' "One per environment" | patch |
| 17 | blind | No promtool check before merge, CI checks the backend only | low | True; a bad file fails the platform deploy loudly before `up` and leaves the stack untouched; a CI job is new machinery in Vlad's CI | reject |
| 18 | blind | README Platform row lacks the tailnet UI address that the n8n row gives | low | `README.md:33` gives n8n's address | patch |
| 19 | blind | `.memlog.md` line reads as if the backend cleanup were story 2 | low | wording | patch |
| 20 | blind | ADR 22 settles metrics retention, which the spine lists as open, without saying so | low | `ARCHITECTURE-SPINE.md:304` | patch: ADR 22 Consequences |

## Design Notes

- **ADR number.** SPEC.md and stories.yaml say "ADR 21"; 0021 was taken by the backend cleanup on 2026-11-18. This story writes 0022 and fixes those mentions.
- **Retention by time and size.** `/srv/data` is one volume shared with prod; `retention.size=1GB` bounds disk if series ever multiply. Setting the size alone turns off the 15-day time default (checked 2026-11-19: runtime info shows `1GiB` instead of `15d`), so `retention.time=15d` is set explicitly; whichever limit hits first applies.
- **promtool before `up`.** On SIGHUP a bad config is only logged and the old one keeps running, so the deploy would stay green; on a recreate it would exit and take Prometheus down. Checking in a throwaway container first fails the deploy before anything changes, like `caddy reload` refuses a bad Caddyfile.
- **Story 3** adds `--query.timeout` and `--query.max-samples` to the same `command` and joins Grafana to `observability`.

## Verification

**Commands:**
- `docker compose --file deploy/platform/compose.yml config --quiet` and the same for `deploy/app/compose.yml` with the variables they require set to dummies -- expected: no error.
- `cd backend && uv run pytest tests/test_grafana_dashboards.py` -- expected: green (it reads `compose.yml`).

**Manual checks:**
- After merge: Delivery green; tailnet `:9090/targets` shows `api` up `env="dev"`; `curl https://backend-showcase-dev.duckdns.org/metrics` is 404; `/health` ok.

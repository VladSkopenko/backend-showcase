# 22. Prometheus in the platform stack scrapes dev

Date: 2026-11-19

## Status

Accepted. Tracked in [issue #26](https://github.com/VladSkopenko/backend-showcase/issues/26).
Amends the architecture spine's Metrics convention: the API's metrics port is reachable over
`edge` as well as `observability`, and Caddy is its boundary. Amended 2026-11-19: the public
Grafana reads Prometheus through a second data source, and every query is bounded. Amended
2026-11-19 again, following [ADR 23](0023-observability-ends-with-logs.md): Prometheus also
scrapes the host's node exporter.

## Context

The API counts its requests by method, route template and status and serves them on
`METRICS_PORT` (9000), a port separate from the one Caddy proxies
([ADR 7](0007-single-vm-platform-and-app-stacks.md)). Nothing collects them yet. The platform
stack ([ADR 15](0015-platform-as-code.md)) is where Prometheus belongs, and the public Grafana
([ADR 19](0019-public-grafana-reads-dev.md)) is where the numbers will be shown. Only dev has live
traffic: the booking simulator runs there ([ADR 14](0014-booking-simulator-on-dev.md)).

The spine says the metrics port is "reachable only over `observability`". The API container is
also on `edge`, where Caddy reaches it, and a container port is open on every network the
container joins.

## Decision

- **One Prometheus in the platform stack, scraping dev.** Image `prom/prometheus:v3.15.1`, one
  scrape job `api` with the static target `app-dev-api:9000` every 15 seconds, plus job `node`
  for the host (below). Staging and production get API targets when they go live.
- **`env` comes from the scrape config.** The job sets `env: dev` on its target. The application
  never sets it, because one image is promoted by digest across environments
  ([ADR 4](0004-image-identity-and-promotion.md)).
- **One `observability` network for every environment.** It is internal and created by both the
  platform and the app deploy scripts, whichever runs first. The one app compose file attaches
  every environment's API to it with the alias `app-<env>-api`, so staging and production join
  on their next deploy without being scraped. Prometheus joins `observability` and the platform's
  `default` network, never `edge`.
- **The UI is on the tailnet only.** The tailscale service serves it on
  `https://<PLATFORM_HOST>:9090` with a `*.ts.net` certificate. No Caddy site and no published
  port.
- **Caddy is the boundary of the metrics port.** Caddy proxies only port 8000 of each API, so
  `/metrics` is not served on any public host. Over `edge`, Caddy, Grafana and the other
  environments' APIs can reach port 9000, as they already reach port 8000; the series hold no
  ids, paths or personal data.
- **API and host series only.** Prometheus scrapes the dev API (job `api`) and the host's node
  exporter (job `node`), nothing else, itself included. Once Grafana reads it, an anonymous Viewer
  can send any PromQL to it, as with SQL in ADR 19.
- **The host through node_exporter.** `prom/node-exporter:v1.13.1` in the platform stack, on
  `observability` only, reads the host's root mounted read-only at `/host`. Only the `cpu`,
  `meminfo`, `loadavg`, `filesystem` and `diskstats` collectors run, and the exporter's own Go and
  process metrics are off. No host network, so no network traffic metrics. The target carries no
  `env`: one VM serves every environment. The data source keeps its name "API metrics
  (Prometheus)": renaming a provisioned source with the same uid stops Grafana at its next start,
  and provisioning is read only at start.
- **Config reloads by signal.** `prometheus.yml` is mounted read-only from the repository. The
  platform deploy checks it with `promtool` in a throwaway container before `up`, so a bad file
  fails the deploy before anything changes, and sends `SIGHUP` after `up`, because compose does
  not recreate a container for a changed mounted file. The lifecycle API stays off, so nothing
  over HTTP can reload or stop Prometheus.
- **The public Grafana reads Prometheus.** A second data source, uid `prometheus`, not the default,
  so the dev database stays the default for Explore and new panels. Grafana joins
  `observability`. The dashboard `api` (requests per second by route, 5xx share, p50 and p95
  latency by route, responses by status, an `env` variable) is a file next to the five SQL
  dashboards and carries their tag, so their Dashboards menu lists it. Latency leaves out
  `/health` and the two streamed assistant routes, whose duration is the length of a chat turn.
- **Every query is bounded.** `--query.timeout=10s`, `--query.max-concurrency=4` and
  `--query.max-samples=1000000`, with `mem_limit` 512m. The defaults (2 minutes, 20 at once,
  50 million samples) let one visitor exhaust the memory limit. Sized in a local dry run with 15
  days of history over 705 latency buckets: with every panel pinned to 500 data points, the
  15-day p95 panel peaks at about 540 thousand samples, and four queries at the sample limit at
  once finish in about 5 seconds at 512m but take nearly the timeout at 256m. Pinned points make
  a query's size depend on the number of series rather than the range, so the default 3-hour view
  is of the same order; the limit fits about 1,300 latency buckets, about 85 routes with
  traffic.
- **Retention is bounded by time and size.** 15 days or 1 GB, whichever is reached first, set in
  the config file: the 3.15 command-line flags for retention are deprecated. `/srv/data` is one
  volume shared with production.

## Alternatives considered

- **The API off `edge`.** Caddy reaches the API on `edge` by design (AD-13), so the API stays
  there and so does the open metrics port.
- **Bind the metrics server to the `observability` interface only.** The container's address on
  that network is assigned by Docker at start, and the application would have to know about the
  platform's network layout.
- **A network per environment, like `analytics-<env>`.** Prometheus would join three networks for
  one job each; one network matches AD-13 and one Prometheus for all environments.
- **Block Prometheus's status endpoints in Caddy.** Would keep the version and config private. It
  needs rules on both Grafana paths that forward to Prometheus, and nothing in those endpoints is
  secret.
- **`--web.enable-lifecycle` and `POST /-/reload`.** Opens reload and shutdown over HTTP to anyone
  who can reach the port, which Grafana's data source proxy will make public in effect.

## Consequences

- A dev deploy recreates the API container once to attach it to `observability`, and staging and
  production do the same at their next promotion.
- When the platform deploys before dev, or dev is down, the target is down; neither deploy
  depends on the other (AD-14).
- A Prometheus config error found by `promtool` fails the platform deploy and leaves the stack
  untouched. An error `promtool` cannot see, such as an unreachable target, shows only on the
  targets page.
- Every container on `edge` or `observability` can read the metrics of every environment's API,
  including one environment's API reading another's.
- "Tailnet only" holds for people, not containers: Prometheus answers on port 9090 without
  authentication to every container on `observability`, every environment's API included, and on
  the platform's `default` network.
- Metrics retention, left open in the spine's deferred list, is settled here; log retention stays
  open.
- Through the data source an anonymous visitor reads Prometheus's exact version, its whole
  configuration, its flags and its targets (`app-dev-api:9000`, `node-exporter:9100`), on both
  `/api/datasources/proxy/uid/prometheus/` and `/api/datasources/uid/prometheus/resources/`. ADR 19
  hides Grafana's own version; Prometheus's is disclosed here. None of it is secret.
- One load of the dashboard sends five range queries and the variable query, more than the four
  slots, so concurrent visitors queue behind each other, and a visitor holding the slots delays
  everyone's panels until the 10-second timeout; the limits protect Prometheus, not the
  dashboard's responsiveness.
- If the API's routes grow past about 85 with traffic, the latency panel exceeds the sample limit
  and shows an error in any range, and `--query.max-samples` with `mem_limit` need measuring
  again. Changing the panels' 500 data points has the same effect.
- `rate` needs two samples, so the first request of a new series, such as a route's first 5xx,
  never shows; on a quiet dev rare errors can be missed.
- An anonymous visitor reads the node exporter's version (`node_exporter_build_info`), the host's
  and the exporter container's mountpoints and filesystem types, and the disk device names. Disk
  models and serials stay empty: the exporter has no udev data.
- node-exporter:9100 answers without authentication to every container on `observability`,
  every environment's API included.

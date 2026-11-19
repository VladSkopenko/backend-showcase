# 22. Prometheus in the platform stack scrapes dev

Date: 2026-11-19

## Status

Accepted. Tracked in [issue #26](https://github.com/VladSkopenko/backend-showcase/issues/26).
Amends the architecture spine's Metrics convention: the API's metrics port is reachable over
`edge` as well as `observability`, and Caddy is its boundary.

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
  scrape job `api` with the static target `app-dev-api:9000` every 15 seconds. Staging and
  production get targets when they go live.
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
- **API counters only.** Prometheus scrapes nothing else, itself included. Once Grafana reads it,
  an anonymous Viewer can send any PromQL to it, as with SQL in ADR 19.
- **Config reloads by signal.** `prometheus.yml` is mounted read-only from the repository. The
  platform deploy checks it with `promtool` in a throwaway container before `up`, so a bad file
  fails the deploy before anything changes, and sends `SIGHUP` after `up`, because compose does
  not recreate a container for a changed mounted file. The lifecycle API stays off, so nothing
  over HTTP can reload or stop Prometheus.
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

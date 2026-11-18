---
id: SPEC-gh-26-api-metrics
companions:
  - gotchas.md
  - ../../../docs/adr/0007-single-vm-platform-and-app-stacks.md
  - ../../../docs/adr/0019-public-grafana-reads-dev.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# API metrics in Prometheus, shown live on the public Grafana

## Why

A vision to realize and a gap to close: the showcase's public Grafana shows only business data from the dev database, so nobody sees how the API itself behaves. Issue #26 step "Prometheus with its targets" is open, and ADR 7 already fixes where metrics live. Live request rate, errors and latency on the public Grafana make the observability part of the project visible to a visitor.

## Capabilities

- **CAP-1**
  - **intent:** Prometheus can read the API's request count, status and latency per full route template from a port the public host never serves.
  - **success:** the metrics port serves `http_requests_total{method,route,status}` and `http_request_duration_seconds{method,route}` with templates like `/api/v1/bookings/{booking_id}`; `/metrics` on the public dev host is 404.
- **CAP-2**
  - **intent:** A Prometheus in the platform stack collects the dev API's metrics labelled `env="dev"`, its UI reachable only over the tailnet.
  - **success:** the Prometheus UI over the tailnet shows target `api` up with `env="dev"`; no public host serves it.
- **CAP-3**
  - **intent:** An anonymous visitor of the public Grafana sees the dev API's live request rate, 5xx share, latency and responses by status.
  - **success:** dashboard `api` on the public Grafana shows dev data in four panels: requests per second by route, 5xx share, p50/p95 latency by route, and responses by status, with an `env` variable. Latency panels leave out `/health` and both SSE routes.

## Constraints

- The metrics port (`METRICS_PORT`, default 9000) is never proxied by Caddy and port 8000 gains no `/metrics` (ADR 7, AD-13). The port is also reachable over `edge`, so Caddy is the real boundary; ADR 21 records this and amends the spine's Metrics convention.
- Labels are only `method`, `route`, `status`. `route` is the full template or `unmatched` (no API route handled the request: unknown paths and the docs pages), taken from an explicit table built in `create_app` from the (router, prefix) list, with `prometheus-client` (Vlad, option a, 2026-11-18). FastAPI 0.162's `scope["route"]` lacks the include prefix, and its private effective-route context is not used.
- No ids, raw paths, query strings or personal data in any series.
- `env` comes from the Prometheus scrape config, never from the app: one image is promoted by digest across environments.
- Apps never depend on the platform (AD-14): the API serves when nothing scrapes it, and a dev deploy works with the platform down.
- Anonymous Grafana Viewers can send any PromQL through the data source proxy, as with SQL in ADR 19. Prometheus therefore holds API counters only, its query timeout and max samples are lowered, and ADR 21 records this.
- Fixed values:
  - Prometheus 3.15.x, per the spine's version table.
  - Its UI is on the tailnet at port 9090.
  - It scrapes `app-dev-api:9000` every 15 s over the internal network `observability`, which the API joins as `app-<env>-api`.
  - The Grafana data source has uid `prometheus` and is not the default.
- Platform services follow issue #26's shape and deploy from `main` through `delivery.yml`: init data directory, `mem_limit`, healthcheck, read-only config from the repository, tailnet UI via `serve.json`, no new secrets.
- Infrastructure files are written one file per step with Vlad, every key checked in the official docs, with a local dry run first.

## Non-goals

- Node, Postgres and Redis exporters.
- Alertmanager, alert rules and the n8n readiness probe.
- Staging and prod targets (not live yet).
- OpenTelemetry and traces.
- Process and platform collectors in the API.
- Prometheus on a public host.

## Success signal

- A visitor opens the public Grafana, picks the API dashboard and watches the rate and latency move as the n8n bots book on dev, while `https://backend-showcase-dev.duckdns.org/metrics` answers 404.

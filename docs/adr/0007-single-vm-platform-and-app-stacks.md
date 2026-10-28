# 7. One VM runs a platform stack and an app stack per environment

Date: 2026-10-28

## Status

Accepted

## Context

The $0 budget allows one Oracle Always Free A1 VM: 2 OCPUs and 12 GB of RAM since June 2026. That VM
has to host three environments, monitoring, logs, traces and n8n. App deploys must not restart
monitoring, and environments must stay apart from each other.

## Decision

- The platform stack (Caddy, Prometheus, Alertmanager, Grafana, VictoriaLogs, Tempo, n8n) is one compose
  project. It is deployed by its own workflow when `deploy/platform/` changes.
- Each environment is its own compose project, `app-<env>`. A deploy touches only its own project.
- App stacks never depend on the platform. They declare no `depends_on` on platform services, and
  exporting telemetry is fire-and-forget.
- Three shared Docker networks connect the layers. Everything else stays on each project's private
  network.
  - `edge`: Caddy, n8n and each environment's API container.
  - `observability`, internal: Prometheus, Grafana, Tempo and VictoriaLogs, plus each environment's
    API, `postgres_exporter` and `redis_exporter`. The exporters run inside the app projects.
  - `analytics`, internal: Grafana and production PostgreSQL only. Grafana reads it through a
    read-only role for business dashboards.
- The API serves `/metrics` on a separate port that Caddy never proxies.
- n8n serves all environments. Each workflow takes the environment as a parameter, and webhooks use
  `/webhook/<env>/<event>`.
- Only the environment hosts and Grafana are public, each on its own DuckDNS subdomain (4 of 5). Each
  host routes entirely to one stack. Prometheus, Alertmanager, VictoriaLogs, Tempo and n8n are
  reachable only through the tailnet.

## Alternatives considered

- **One VM per environment.** The free tier cannot afford it.
- **One shared multi-target `postgres_exporter` in the platform stack.** It cannot reach databases on
  private networks unless they all join a shared network. Dev containers could then reach production
  data.
- **k3s with Helm.** Kept as a stretch goal. It would replace the compose projects but not the
  layering.

## Consequences

- A platform restart does not take environments down, and an app deploy does not restart monitoring.
- Production data is reachable only from the prod project and from Grafana's read-only role.
- One VM is a single point of failure for everything. [ADR 9](0009-alerting-from-outside-the-vm.md)
  makes sure that failure is at least noticed.

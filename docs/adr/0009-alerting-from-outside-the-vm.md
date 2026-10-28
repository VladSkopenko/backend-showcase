# 9. Alerting must work when the VM does not

Date: 2026-10-28

## Status

Accepted

## Context

Prometheus and Alertmanager live on the same VM they watch, so if the VM dies, nothing reports it. n8n
runs the kitchen simulator that moves demo orders forward. If n8n stops, visitors can no longer finish
the flow, and a dead n8n cannot report its own death either.

## Decision

- Alertmanager sends alerts to a Telegram bot.
- Alertmanager's always-firing Watchdog alert pings healthchecks.io. When the pings stop, healthchecks.io
  sends the alert itself, which covers a dead host, a dead Alertmanager or a broken network.
- Prometheus probes n8n at `/healthz/readiness`, which reports whether n8n can reach its database, not
  just whether the process is alive.
- The API exposes the age of the oldest order still in `placed` as a gauge. A production alert fires
  when it exceeds 15 minutes, whatever the reason the kitchen stopped: n8n down, the workflow switched
  off, or a broken API call.

## Alternatives considered

- **n8n reporting its own failures.** It cannot report while it is down.
- **Prometheus querying PostgreSQL for stuck orders.** Prometheus has no SQL source. A separate SQL
  exporter would duplicate what the API already knows.

## Consequences

- Every failure that breaks the demo, at any layer, produces a Telegram message within minutes.
- healthchecks.io becomes an external dependency, on its free plan.

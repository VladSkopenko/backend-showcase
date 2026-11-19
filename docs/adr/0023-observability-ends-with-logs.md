# 23. Observability ends with logs

Date: 2026-11-19

## Status

Accepted. Tracked in [issue #26](https://github.com/VladSkopenko/backend-showcase/issues/26).
Supersedes [ADR 9](0009-alerting-from-outside-the-vm.md). Amends
[ADR 7](0007-single-vm-platform-and-app-stacks.md), [ADR 15](0015-platform-as-code.md) and the
architecture spine, as listed below.

## Context

[ADR 9](0009-alerting-from-outside-the-vm.md) planned alerting that works when the VM does not:
Alertmanager sending to Telegram, a Watchdog that pings healthchecks.io, Prometheus probing n8n,
and a gauge of the oldest order still in `placed`. ADR 7, ADR 15 and the spine add Tempo for
traces to the platform, and ADR 7 and AD-13 a `redis_exporter` in every app project. Since then the
final scope stopped at the pre-order: there are no orders and no kitchen to watch, and Redis was
never deployed. Prometheus and the public Grafana already show the dev API
([ADR 22](0022-prometheus-scrapes-dev.md)), and the exporters for the VM and dev PostgreSQL are
planned next. On 2026-11-19 the observability phase was set to end with logs.

## Decision

- **What stays.** Prometheus and the public Grafana; node_exporter for the VM in the platform
  stack, on `observability` with the host's root mounted read-only and no host network, so without
  network traffic metrics; postgres_exporter for dev PostgreSQL inside the dev app project, never
  in the platform stack, which ADR 7 rejects; VictoriaLogs and log shipping as the last
  observability step. Staging and production API targets come with those environments' go-live,
  as ADR 22 says.
- **What is dropped.** Alertmanager, alerts to Telegram and the healthchecks.io watchdog; the
  Prometheus probe of n8n's `/healthz/readiness` (n8n's own readiness healthcheck in the platform
  compose stays); the gauge of the oldest `placed` order, since there are no orders; Tempo and
  traces; `redis_exporter`, since Redis is not deployed.
- **ADR 7 and AD-13 amended.** postgres_exporter runs in the dev app project only, not in every
  app project; node_exporter runs in the platform stack on `observability`; there is no
  `redis_exporter`. The platform list, the `observability` members and the tailnet-only services
  lose Alertmanager and Tempo. The consequence "ADR 9 makes sure that failure is at least
  noticed" no longer holds; see Consequences.
- **ADR 15 amended.** Its platform service list loses Alertmanager and Tempo.
- **Spine amended.** AD-16 ("Alerting works when the VM does not") is dropped. AD-14 keeps its rule
  with "exporting logs is fire-and-forget", without traces. The Health convention loses the
  Prometheus probe of n8n. AD-15 no longer binds alerting. The scope's "alerting", the platform
  rows of the stack and repository tables, the version pin for Tempo, the tailnet list and the
  diagram nodes for Alertmanager, Telegram, healthchecks.io and Tempo describe parts that will not
  be built.

## Alternatives considered

- **Alertmanager without Telegram.** Alerts nobody receives add a service and rules to maintain
  for no reader.
- **Alerts through Grafana.** Grafana's alerting would need a contact point and a way to stay
  silent when Grafana itself is down, which brings back the watchdog problem of ADR 9.
- **An external uptime monitor on the public `/health`.** Free and with nothing on the VM, but
  another account and notification channel outside the repository; left out with the rest of
  alerting.
- **Traces in Tempo.** One API on one VM; request metrics and logs answer the questions a visitor
  of the showcase can ask.

## Consequences

- A dead VM, a dead n8n or a stopped simulation is noticed only by a person looking at the public
  Grafana, the n8n editor or the API.
- A broken deploy still fails its Delivery run, because each deploy waits for the API's
  healthcheck; GitHub reports the failed run. Nothing reports a later failure of a running
  environment.
- No external dependency on healthchecks.io and no Telegram bot token to keep.
- The spine still describes the dropped parts; this ADR is where they are amended.

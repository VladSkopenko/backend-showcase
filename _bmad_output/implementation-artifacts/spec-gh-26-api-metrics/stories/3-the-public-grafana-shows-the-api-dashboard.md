---
title: 'The public Grafana shows the API dashboard'
type: 'feature'
created: '2026-11-19'
status: 'done'
baseline_commit: 'c341b46f8ee029d54be1179073e8da7d65579421'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-api-metrics/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-api-metrics/gotchas.md'
  - '{project-root}/docs/adr/0022-prometheus-scrapes-dev.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Prometheus collects the dev API's request metrics (story 2), but only over the tailnet; a visitor of the public Grafana still sees business data only.

**Approach:** Add Prometheus as a second, non-default Grafana data source (uid `prometheus`) and a provisioned dashboard `api` with four panels and an `env` variable. Because anonymous Viewers can send any PromQL through the data source proxy, lower Prometheus's query limits and record this in ADR 22.

## Boundaries & Constraints

**Always:** Data source: type `prometheus`, uid `prometheus`, `http://prometheus:9090`, access proxy, `isDefault: false`, `editable: false`, scrape interval 15s declared so `$__rate_interval` covers at least four scrapes. Grafana joins `observability`. Dashboard `api.json` in `deploy/platform/grafana/dashboards`, `editable: false`, timezone `Asia/Tbilisi`, every panel and the variable on uid `prometheus`. Variable `env` from `label_values(http_requests_total, env)`, default `dev`. Panels, titled exactly: "Requests per second by route"; "5xx share", computed as `(sum(5xx rate) or vector(0)) / sum(rate)` with the parentheses, so it is 0 rather than empty without 5xx; "Latency p50 and p95 by route", one panel with p50 and p95 targets by route, each excluding `/health`, `/api/v1/assistant/sessions/{session_id}/messages` and `/api/v1/assistant/sessions/{session_id}/actions/{action_id}/apply` as three exact `route!="..."` matchers; "Responses by status". Every panel target filters `env="$env"`; every range selector in a panel target is `[$__rate_interval]`; panels pin `maxDataPoints`, so the 15-day query size does not depend on the browser's width. Prometheus `command` gains `--query.timeout`, `--query.max-samples` and `--query.max-concurrency` below their defaults (2m, 50000000, 20), sized so that Prometheus's baseline plus four concurrent queries at the sample limit stay inside `mem_limit`. Infrastructure files are written with Vlad one file per step, every key checked in the official docs with a link, after a local dry run in throwaway containers.

**Decisions (Vlad, 2026-11-19):** default range last 3 hours, auto-refresh 30 s; tag `restaurant` and the same dashboards-by-tag link as the SQL dashboards, so `api` appears in their Dashboards menu; the Prometheus status endpoints that the data source makes public (buildinfo, config, flags, targets) are accepted and recorded in ADR 22, with no Caddy block.

**Never:** No change to the five SQL dashboards' queries, the Postgres data source or the start page. No new secret. No Grafana alerting, no other Prometheus job, no exporters. No staging or prod data. No Grafana access to Prometheus's admin or lifecycle endpoints (both stay off).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Visitor | anonymous, opens dashboard `api` | four panels with dev data, `env=dev` | N/A |
| No errors | no 5xx in the range | 5xx share shows 0 | N/A |
| Some errors | 1 of 10 responses is 5xx | 5xx share shows 0.1 | N/A |
| Latency | SSE turn of 30 s on dev | latency panel unchanged; rate and status panels count it | N/A |
| Heavy query | Viewer sends a PromQL over too many samples or for too long | Prometheus aborts it; Grafana shows the error | Prometheus stays up within `mem_limit` |
| Prometheus down | platform up, Prometheus stopped | API panels show a data source error; SQL dashboards work | none |
| Data source picker | Viewer opens Explore | Postgres stays the default data source | N/A |

</frozen-after-approval>

## Code Map

- `deploy/platform/grafana/provisioning/datasources/postgres.yaml` -- one data source per file, `editable: false`, `isDefault: true`; the new file follows it. Grafana applies provisioning at start only (`deferred-work.md`: restart for data source changes); joining `observability` recreates the container, which applies it.
- `deploy/platform/grafana/provisioning/dashboards/dashboards.yaml` -- file provider polls `/etc/grafana/dashboards` every 30 s; a new JSON file needs nothing else.
- `deploy/platform/grafana/dashboards/checks.json` -- shape to copy: `uid`, `title`, `description`, `tags`, `editable`, `timezone`, `time`, `refresh`, `schemaVersion: 42`, `links` (dashboards by tag), `templating`, `panels` with `datasource` on panel and target.
- `backend/tests/test_grafana_dashboards.py:248-251` -- `test_the_directory_holds_exactly_the_five_dashboards` compares the whole directory to the five SQL uids; it must allow `api.json`. Parametrized tests run over the SQL uids only (`UIDS` from `PANEL_TITLES`), so they stay as they are.
- `backend/src/app/infrastructure/metrics/request_metrics_middleware.py:19-30` -- `http_requests_total{method,route,status}` (exposed also as `http_requests_created`) and `http_request_duration_seconds{method,route}` (`_bucket`, `_sum`, `_count`, `_created`).
- `deploy/platform/compose.yml` -- `grafana.networks` is `edge`, `analytics-dev`; `prometheus.command` holds the two paths; `mem_limit: 256m`.
- `docs/adr/0022-prometheus-scrapes-dev.md` -- "API counters only" bullet already names anonymous PromQL; the amendment adds Grafana and the limits.
- Live 2026-11-19: 231 dev series after ten minutes, 165 of them histogram buckets, 11 routes; the app has 43 route templates, so 600-750 bucket series are plausible later.
- `backend/pyproject.toml` -- mypy `strict`, no `types-PyYAML`: tests read YAML files with regex, like `test_the_start_page_is_a_dashboard_in_the_directory_the_provider_reads`.
- Grafana answers a proxied Prometheus `POST` outside its allow-list with 403 itself, so admin endpoints are not a useful probe; `api/v1/status/flags` answers anonymously and shows the flags.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_grafana_dashboards.py` -- the directory holds the five SQL dashboards and `api.json`; new tests for `api.json`: uid, tag `restaurant` and the dashboards-by-tag link, time range `now-3h` to `now`, refresh `30s`, timezone, `editable: false`, exactly the four panel titles, the latency panel has two targets whose `expr` contain `histogram_quantile(0.5,` and `histogram_quantile(0.95,` respectively, each grouping `by (le, route)`, while the rate and status targets contain no `route!=` matcher, variable `env` with query `label_values(http_requests_total, env)` and default `dev`, every panel, target and variable on uid `prometheus`, every panel target (not the variable query, which may be stored as a string or an object) filters `env="$env"`, both latency targets contain the three exact `route!="..."` matchers, the 5xx share expression contains `or vector(0)) /`, every range selector `[...]` in a panel target is `[$__rate_interval]`, every panel sets the same `maxDataPoints`, expression rules apply to `target["expr"]` with whitespace collapsed and string literals removed, except the `route!=` and `env="$env"` checks, which read the literals; every metric name (the identifier right before `{`) is `http_requests_total`, `http_requests_created`, or `http_request_duration_seconds` with `_bucket`, `_sum`, `_count` or `_created`; the data source file, read with regex, has uid `prometheus`, `type: prometheus`, `access: proxy`, `url: http://prometheus:9090`, `isDefault: false`, `editable: false`, and `timeInterval: 15s` as an indented key under `jsonData:` -- tests first.
- [x] Local dry run (scratchpad, throwaway) -- on scratchpad drafts of `prometheus.yaml` and `api.json`, where the `maxDataPoints` value is chosen; the repo files are later written from these drafts one file per step with that value unchanged, so `--query.max-samples` matches the query it was sized on. 15 days of about 750 bucket series at 15 s spacing, each carrying `env="dev"`, `job="api"`, `instance="app-dev-api:9000"`, written as OpenMetrics (timestamps in seconds, ending with `# EOF`, several GB) and backfilled with `promtool tsdb create-blocks-from openmetrics --max-block-duration=24h` into a throwaway TSDB, ending before the last 3 hours; Prometheus with the new flags and the planned `mem_limit` started on it, scraping a stand-in that sends `Content-Type: text/plain; version=0.0.4` for the live part; Grafana 13.2.6 with both provisioning files and `api.json`: every panel query answers through `/api/ds/query` as an anonymous Viewer, 5xx share shows 0 without 5xx and the known share with some; the 15-day p95 request body is taken from the browser's query inspector (it carries the pinned `maxDataPoints` and the frontend's `intervalMs`; a hand-built body gets a different step and window), its step and window are read from `executedQueryString`, and that expr and step replayed against Prometheus with `stats=all` give `peakSamples`, which sets `--query.max-samples` with headroom; four parallel range queries of `http_request_duration_seconds_bucket{env="dev"}`, the step tuned until `peakSamples` is 90-100 % of the limit (confirmed on v3.15.1 in the dry run; an instant `count_over_time` cannot get there, it holds one series' window at a time; the API caps a range query at 11,000 points per series, so above series × 11,000 use `... * 1`, which peaks at about twice the plain selector), leave `.State.OOMKilled` false and `/-/ready` 200, with the `docker stats` peak recorded (Prometheus runs with auto GOMEMLIMIT at 0.9, so pressure may show as slowness rather than a kill), otherwise `mem_limit` is raised; a query over the limit fails while `/-/ready` stays 200, Postgres stays default; finally, with Prometheus stopped, the `api` panel queries return a data source error while one SQL dashboard query through `/api/ds/query` still answers.
- [x] `deploy/platform/grafana/provisioning/datasources/prometheus.yaml` -- the data source.
- [x] `deploy/platform/grafana/dashboards/api.json` -- the dashboard.
- [x] `deploy/platform/compose.yml` -- Grafana joins `observability`; Prometheus `command` adds `--query.timeout=10s`, `--query.max-concurrency=4` and `--query.max-samples` from the dry run; `mem_limit` raised only if the dry run says so.
- [x] `docs/adr/0022-prometheus-scrapes-dev.md` -- amended: Grafana reads Prometheus through a non-default data source; the three limits and why (defaults allow 20 concurrent queries of 50 M samples against `mem_limit`); accepted: a visitor holding the four query slots delays others' panels until the timeout; the first increment of a new series (for example a route's first 5xx) never shows in `rate`/`increase`; the status endpoints public through the data source (exact version, config, flags, targets), which partly undoes ADR 19's version hiding.
- [x] `README.md`, `README.uk.md` -- Dashboards row: six dashboards, the API one from Prometheus (ADR 22).

**Acceptance Criteria:**
- Given the merge to main, when Delivery finishes, then the platform job is green and an anonymous visitor sees dashboard `api` with dev data at `https://backend-showcase-grafana.duckdns.org`.
- Given the public Grafana, when `/api/datasources/proxy/uid/prometheus/api/v1/status/flags` is requested anonymously, then `web.enable-admin-api` and `web.enable-lifecycle` are `false` and the three `query.*` flags carry the deployed values.

## Implementation Notes

- Dry run 2026-11-19 (Docker 29.1.3, arm64; project `s3dry`, torn down; drafts in the scratchpad): backfill of 1000 series (750 bucket, 50 (method, route) pairs, 10 % 5xx) over 15 days at 15 s, 12 GB OpenMetrics, `create-blocks-from openmetrics --max-block-duration=24h` took 31 min, 21 blocks, 86 400 samples per series kept. Stand-in scraped live with growing counters. Through Grafana 13.2.6 `/api/ds/query`, anonymous: every target 200; last 30 min 5xx share 0, a backfill day 0.1; 15-day range step 30m, window `30m15s`, latency 47 routes (the three exclusions work), rate 50; Postgres stays default; `status/flags` anonymous shows the deployed flags; with Prometheus stopped the API targets answer 400 with a data source error and a `restaurant-dev` query answers.
- Sizing: the 15-day p95 replayed with `stats=all` peaks at 538 357 samples over 705 bucket series (the 565 figure for the 3 h view was measured on a stand-in with two live series; with pinned points the real 3 h view is of the same order, see #43). Four parallel plain-selector range queries at about 96 % of the limit: 2 M at 256m all time out at 10 s (memory at the cap, GOMEMLIMIT 0.9); 2 M at 512m pass in 8-10 s, peak 481 MiB; 1 M at 256m pass in 6.5-9.8 s at 255.9 MiB; 1 M at 512m pass in about 5 s, peak 459 MiB (GOMEMLIMIT); never OOM-killed, `/-/ready` 200 throughout; over the limit fails with "would load too many samples". Chosen: `--query.max-samples=1000000` (1.86x the measured 15-day p95) and `mem_limit: 512m`. Only a manually chosen long range can exceed it if routes multiply; the default 3 h view is far below.
- `maxDataPoints` 500 on every panel.

## Spec Change Log

- 2026-11-19, dry run: no browser in this session, so the 15-day request body was not copied from the query inspector; `intervalMs` was computed with Grafana's own `calculateInterval`/`roundInterval` (`packages/grafana-data/src/datetime/rangeutil.ts` at v13.2.6: 15 d / 500 = 30m, min `timeInterval` 15s), and the step and window Grafana applied were read from `executedQueryString` (Step 30m0s, `[30m15s]`, as the third review measured). KEEP: replay with `stats=all` against Prometheus.

## Review Triage Log

| # | Layer | Finding | Verdict | Evidence | Route |
|---|-------|---------|---------|----------|-------|
| 1 | spec review | 5xx share shows "No data" with no 5xx | medium | Empty numerator gives an empty frame (reviewer run); standard PromQL | patch: `or vector(0)` |
| 2 | spec review | First increment of a new series never shows in `rate`/`increase` | low | Reviewer run; `rate` needs two samples | patch: accepted, Design Notes and ADR |
| 3 | spec review | AC's snapshot probe cannot fail for the intended reason | medium | Reproduced: Grafana answers the proxied POST with 403 itself | patch: probe `status/flags` |
| 4 | spec review | Status endpoints (version, config, targets) become public through the data source | medium | Reproduced on 13.2.6: buildinfo, config, targets 200 anonymously on proxy and resources paths | intent: Vlad accepted, ADR 22 |
| 5 | spec review | `\{` in a `route!~` matcher is a PromQL parse error | medium | Reproduced: `unknown escape sequence U+007B` | patch: exact `route!=` matchers |
| 6 | spec review | A YAML-parsing test fails mypy strict (no stubs) | low | `pyproject.toml` strict, no `types-PyYAML` | patch: regex |
| 7 | spec review | Metric-name rule ambiguous | low | allowed `http_requests_total_bucket`, rejected `http_requests_created` | patch |
| 8 | spec review | 1 M samples may not hold for a 15-day p95 with more routes | maybe-false | Reviewer: 950 k-sample subquery already fails; 43 routes possible | patch: measure in the dry run |
| 9 | spec review | One latency panel or two | low | four titles vs plural wording | patch: one panel, two targets |
| 10 | spec review | Stand-in without Content-Type is scraped as down | low | Same as story 2's dry run | patch: dry-run task |
| 11 | spec review | Four query slots let one visitor delay others' panels | low | Engine queues beyond max-concurrency | patch: accepted in ADR |
| 12 | re-review | `A or vector(0) / B` parses as `A or (vector(0) / B)`: the panel shows the 5xx rate, not the share | high | Reproduced: `vector(5) or vector(0) / vector(10)` = 5, parenthesized = 0.5 | patch: parentheses, test, matrix row |
| 13 | re-review | Scraping cannot produce 15 days of data for sizing | medium | Only real-time scrapes; backfill is `promtool tsdb create-blocks-from openmetrics` | patch: dry run backfills |
| 14 | re-review | Peak samples depend on the step, which depends on panel width | medium | Range-query step comes from maxDataPoints / width | patch: pin `maxDataPoints` |
| 15 | re-review | Memory rule ignores baseline; OOM never exercised under four parallel queries | medium | `mem_limit: 256m`, idle 43 MB, GC and encoding not counted | patch: dry run runs four parallel queries |
| 16 | re-review | Four panel titles not named | low | Test cannot pin invented titles | patch: titles in Always |
| 17 | re-review | Data source test checks only uid and default; `$__rate_interval` not required | low | Always rule untested | patch |
| 18 | third review | A hand-built `/api/ds/query` body measures a smaller query than the panel sends | medium | Reviewer on 13.2.6: without `maxDataPoints` step 3h, with it 30m; window follows `intervalMs` only | patch: body from the query inspector, replay with `stats=all` |
| 19 | third review | Backfill with default 2h blocks takes hours at this size; labels must match the scrape | medium | Reviewer: 30 series 5m07s with 2h blocks, 39 s with 24h; `# EOF` required | patch |
| 20 | third review | Backfilled blocks and 15d/1GB retention | false | Reviewer: all 14.9 days kept on start | reject |
| 21 | third review | Four parallel queries named no query; auto GOMEMLIMIT may hide pressure | medium | p95 sits below the limit by its headroom by construction | patch: tunable `count_over_time`, `docker stats` peak |
| 22 | third review | Rate-window rule lets `increase`/`irate`/`[$__range]` through | low | wording | patch: every range selector |
| 23 | third review | env rule conflicts with the variable query | low | `label_values` cannot filter on itself | patch: panel targets only |
| 24 | third review | `timeInterval` regex passes at the top level, where Grafana ignores it | low | regex not anchored | patch: under `jsonData:` |
| 25 | fourth review | Dry run needs `api.json` and the data source before those tasks write them | medium | Always "after a local dry run" vs task order | patch: dry run on scratchpad drafts, `maxDataPoints` fixed there |
| 26 | fourth review | p50/p95 and "by route" testable in different ways | low | test wording | patch: `histogram_quantile(0.5,`/`(0.95,`, `by (le, route)` |
| 27 | fourth review | `access: proxy`, the variable query and unfiltered rate/status targets untested | low | Always items without a failing test | patch |
| 28 | fourth review | Matrix row "Prometheus down" unchecked | low | no dry-run step | patch: end of dry run |
| 29 | fourth review | Substring rules fragile to whitespace and to `{2}` inside string literals | low | test wording | patch: normalise expr, literals removed |
| 30 | fourth review | Design Notes' "fails at 1 M" reads as a planned value | low | stale wording | patch |
| 32 | sixth review | Plain selector peak is capped by the 11,000-points-per-series limit | low | Reviewer on v3.15.1: peak = series × steps exactly; step 15 s over 2 days refused; `SEL * 1` about 2× | patch: fallback clause |
| 31 | fifth review | Instant `count_over_time` never reaches the limit, so the four-query memory check cannot be built | medium | Engine counts one series' input window at a time (`promql/engine.go`); peak about one window plus output | patch: range queries with tuned step |
| 33 | verification-gap, edge | Excluded route literals not tied to the real route templates | medium | Test pinned its own copy; a renamed apply route would pass and stream durations would return | patch: subset of `RouteTemplates(ROUTERS).templates` |
| 34 | verification-gap, blind | PromQL only checked as text, never parsed or evaluated | medium | Dry run evaluated today's expressions once; a later edit could break a panel with green CI | defer: needs Prometheus or promtool in CI (Vlad's) |
| 35 | edge | 5xx share is NaN when no requests arrive | false | The image's HEALTHCHECK requests `/health` every 30 s (`backend/Dockerfile:32`), counted in the denominator | reject |
| 36 | edge | Idle routes give NaN latency series | low | Gaps on idle routes; guarding needs an `and on(route)` join | reject |
| 37 | edge, blind | Metric-name check misses selectors without braces | low | Unlikely edit; a full PromQL identifier scan adds complexity | reject |
| 38 | edge, blind | `env="$env"` checked once per target, not per selector | low | Denominator without env would pass | patch: every selector |
| 39 | edge | Rate/status test ignores `route!~`/`=~` | low | substring `route!=` only | patch: regex |
| 40 | edge | Denominator guard untested | false | same as #35 | reject |
| 41 | edge | Data source regex not scoped to the entry | low | Nested duplicates not in the file; scoping adds code | reject |
| 42 | edge | `env` may resolve empty when Prometheus is down on load | low | Panels fail then anyway; recovers on reload | reject |
| 43 | edge, blind | With pinned 500 points the default 3 h view is not "a few hundred samples"; the value is unpinned in tests | medium | The 565 figure came from a stand-in with two series; size depends on series × points | patch: ADR and compose comment corrected, test pins 500 |
| 44 | blind | README says a test runs every panel query as the role | low | The API panels are PromQL | patch: "every SQL panel" |
| 45 | blind | "UI only on the tailnet" contradicts public PromQL | false | Statement is about the UI, still true; queries through Grafana are in ADR 22 | reject |
| 46 | blind | `httpMethod: POST` not in the spec; comment's reason wrong | low | Default not verifiable in 13.2.6 source; dry run ran with POST | patch: comment only |
| 47 | blind | ADR says the data source undoes ADR 19's version hiding | low | ADR 19 hides Grafana's version, not Prometheus's | patch |
| 48 | blind | One dashboard load exceeds four slots, so visitors queue each other | low | five range queries plus the variable | patch: ADR consequence |
| 49 | blind | Query flags and `mem_limit` not statically tested | low | Test file already reads infra files with regex | patch: compose test |

## Design Notes

- **Limits.** Twenty concurrent queries at the 50 M default could need gigabytes and get Prometheus OOM-killed by one visitor. The sample limit counts intermediate matrices, not only loaded samples (review: `sum_over_time(vector(1)[11d:1s])`, about 950 k samples, already fails under a 1 M limit, the figure first proposed), so it is measured on the 15-day p95 query rather than estimated. `--query.*` flags are not deprecated in 3.15 (checked 2026-11-19), unlike the retention flags.
- **Counters start unseen.** `rate` needs two samples, so a series created at 1 never shows its first request; on a quiet dev this hides rare 5xx. Pre-initialising label sets in the app is out of scope.
- **SPEC.md** lists only timeout and max samples; concurrency is added here for the memory reason above.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_grafana_dashboards.py` -- expected: green (no other session running pytest).
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests` -- expected: clean.
- `docker compose --file deploy/platform/compose.yml config --quiet` with dummy variables -- expected: no error.

**Manual checks:**
- After merge: anonymous browser on the public Grafana opens `api`, four panels with data; the two proxy requests of the AC.

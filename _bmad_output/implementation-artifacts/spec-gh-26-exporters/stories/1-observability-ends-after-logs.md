---
title: 'Observability ends after logs'
type: 'chore'
created: '2026-11-19'
status: 'done'
baseline_commit: '2929cc1c84906521288449f9d8bf2c773020d3c2'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-gh-26-exporters/SPEC.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** ADR 9, ADR 7, ADR 15, the spine, the roadmap, the README and issue #26 still promise Alertmanager, Telegram alerts, a healthchecks.io watchdog, Tempo and Redis exporters, which Vlad dropped on 2026-11-19: observability ends with the exporters and VictoriaLogs.

**Approach:** ADR 23 supersedes ADR 9, records what is dropped and what stays, and amends ADR 7, ADR 15 and the spine through the ADR, as ADR 19 and 22 did. The roadmap, both READMEs and issue #26 are rewritten to match. Documents only.

## Boundaries & Constraints

**Always:** ADR 23 "Observability ends with logs" (status Accepted, supersedes ADR 9) lists the dropped parts: Alertmanager, Telegram, the healthchecks.io watchdog, the Prometheus probe of n8n readiness, the oldest-placed-order gauge (no orders in the final scope), Tempo and traces, `redis_exporter` (no Redis). It keeps: Prometheus, Grafana, node_exporter and a dev-only postgres_exporter (this initiative), VictoriaLogs next; staging and prod API targets come with their go-live in Phase 3 (ADR 22); n8n's own readiness healthcheck in the platform compose stays, only the Prometheus probe goes. Amendments it records: AD-13 and ADR 7 (postgres_exporter on dev only, node_exporter from the platform stack on `observability`, no `redis_exporter`), AD-16 dropped, AD-14's "exporting traces" clause, the Health convention's Prometheus probe of n8n, every spine, ADR 7 and ADR 15 service list, table row, version pin and diagram node for Tempo, Alertmanager, Telegram and healthchecks.io, and ADR 7's consequence "ADR 9 makes sure that failure is at least noticed", replaced by ADR 23's: a dead VM or n8n is noticed only by a person. ADR 9 gets "Superseded by ADR 23" and ADR 7 and 15 a Status line "Amended by ADR 23", like ADR 18 for ADR 21 and ADR 7 for ADR 19; their bodies stay as written. The dev Prometheus item of the roadmap and step of issue #26 are ticked only when the exporters are live (story 3); the staging and prod targets stay a separate, open item. Issue #26 is edited only after Vlad's go-ahead on the exact text.

**Never:** No change to the spine file itself (amended through the ADR, as ADR 19 and 22 did). No infrastructure, compose, workflow or code change. No promise removed for staging and prod targets. No commitment on whether logs are public on Grafana: that belongs to the VictoriaLogs spec. ADR 22 is not amended here. Redis mentions outside exporters (ADR 6, local compose, CI services in the roadmap) stay; they are another topic.

</frozen-after-approval>

## Code Map

- `docs/adr/0009-alerting-from-outside-the-vm.md` -- Status `Accepted`; becomes "Superseded by ADR 23".
- `docs/adr/0007-single-vm-platform-and-app-stacks.md:7-10,20,28-29,36,52` -- Status lists amendments (ADR 19, ADR 22); platform list with Alertmanager and Tempo, `observability` members with `redis_exporter`, tailnet list, consequence "ADR 9 makes sure that failure is at least noticed".
- `docs/adr/0015-platform-as-code.md:7-8,13,50` -- service list with Alertmanager and Tempo.
- `docs/adr/0021-decisions-by-email-only.md` and README ADR row 18 -- the superseding pattern to copy.
- Spine `ARCHITECTURE-SPINE.md:7,26-27,60,122,131,135,139-143,173,193,205-215,236-237,292` -- mentions the ADR's amendment list names (131 AD-14 traces, 173 Health convention n8n probe, 236-237 diagram `AM --> TG`, `AM -.->|Watchdog| HC`).
- `docs/roadmap.md:61,63-64,113-122` -- Metrics row (Redis exporters), Logs and traces row (Tempo), Alerts row, Phase 4 list and Done-when.
- `README.md:100,147`, `README.uk.md:100,147` -- ADR 9 row, "What is next" observability line.
- Issue #26 body -- Goal ("Adding a platform service (n8n, Prometheus, Alertmanager, VictoriaLogs, Tempo, Grafana)"), Why ("the same manual steps six times") and the steps list (Prometheus, VictoriaLogs, Grafana, Tempo, Alertmanager).

## Tasks & Acceptance

**Execution:**
- [x] `docs/adr/0023-observability-ends-with-logs.md` -- new ADR: Context (ADR 9's plan, the final scope), Decision (dropped, kept, amendments), Alternatives (Alertmanager without Telegram; alerts through Grafana), Consequences (a dead VM or n8n is noticed only by a person; no watchdog).
- [x] `docs/adr/0009-alerting-from-outside-the-vm.md` -- Status "Superseded by ADR 23".
- [x] `docs/adr/0007-single-vm-platform-and-app-stacks.md`, `docs/adr/0015-platform-as-code.md` -- Status lines "Amended by ADR 23: ..."; bodies unchanged.
- [x] `docs/roadmap.md` -- Metrics row "app, node and Postgres exporters"; Logs row without Tempo; Alerts row removed; Phase 4 list: done items ticked (`/metrics`, platform stack separate, Grafana dashboards), "Prometheus scraping dev with node and Postgres exporters" (unticked until story 3) and a separate unticked "Staging and prod targets with their go-live (Phase 3, ADR 22)", the logs item reading exactly "Structured JSON logs in VictoriaLogs", the alert item removed; Done-when: a visitor sees the dev API's metrics and the server's health on the public Grafana, and the logs land in VictoriaLogs.
- [x] `README.md`, `README.uk.md` -- ADR row 9 "Superseded by ADR 23. ..." ("Замінено ADR 23. ..." in Ukrainian, as row 18), new row 23; "What is next" observability line without alerts.
- [ ] Issue #26 -- Goal and Why without Alertmanager and Tempo ("four services"); Grafana step ticked; Prometheus step narrowed to dev with node and Postgres exporters, ticked in story 3, plus a line that staging and prod targets come with their go-live (ADR 22); Tempo and Alertmanager steps marked dropped with a link to ADR 23; edited with `gh issue edit` after Vlad approves the text.

**Acceptance Criteria:**
- Given the merged change, when a reader searches the README, roadmap and ADRs for Telegram, Alertmanager, Tempo or healthchecks.io as whole words, then every hit is in ADR 7, 9, 15 (bodies kept as written) or 23.
- Given issue #26, when it is opened, then its steps match ADR 23.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Evidence | Route |
|---|-------|---------|---------|----------|-------|
| 1 | spec review | grep and AC cannot pass: `tempo` matches "temporary" (ADR 19); ADR 7/15 bodies keep the names | high | grep run; precedent ADR 7 body after ADR 19 | patch: `-w`, allowed-file list, bodies kept |
| 2 | spec review | CAP-4's Prometheus tick has no story | medium | stories 2-4 have no tick task | patch: story 3 ticks roadmap and issue |
| 3 | spec review | Issue #26 Goal and Why name Alertmanager and Tempo | medium | `gh issue view 26` | patch |
| 4 | spec review | Spine mentions 131, 173, 236-237 missing | medium | spine lines | patch |
| 5 | spec review | ADR 22 listed as amended but nothing in it changes | medium | ADR 22:27-29 already says go-live | patch: removed |
| 6 | spec review | Done-when promised public logs, an open VictoriaLogs question | medium | ADR 7:36, roadmap:66 keep it on the tailnet | patch |
| 7 | spec review | `deploy/platform/compose.yml:104` cites ADR 9 | low | file line | moved to story 2, which edits that file with Vlad |
| 8 | spec review | Ukrainian ADR row wording | low | README.uk.md:109 "Замінено" | patch |
| 9 | re-review | stories.yaml still lists ADR 22 for story 1 | medium | story 1 Never says ADR 22 is not amended | patch |
| 10 | re-review | ADR 7 amendment list misses its platform, observability, tailnet lists and the ADR 9 consequence | medium | origin/main ADR 7:20,28,36,52 | patch |
| 11 | re-review | Ticking the Prometheus item would tick staging and prod targets | medium | combined roadmap item | patch: separate open item, issue line |
| 13 | final check | Compose comment task contradicts "documents only" | medium | Never vs last task | patch: moved to story 2 |
| 12 | re-review | Logs item rewrite would keep "linked from Grafana" | medium | roadmap:118 | patch: exact text |
| 14 | code review: edge | node_exporter on `observability` reports container network | low | Vlad's decision; ADR 23 did not say it | patch: ADR 23 states no host network, no traffic metrics |
| 15 | code review: edge | Done-when silent on the open staging/prod item | low | roadmap Phase 4 | patch: Done-when names Phase 3 |
| 16 | code review: blind | ADR 23 Context puts `redis_exporter` in ADR 15 and the platform | medium | ADR 15 has no Redis; ADR 7/AD-13 place it in app projects | patch |
| 17 | code review: blind | Where the dev-only postgres_exporter runs is unstated | medium | ADR 7 rejects a platform-side exporter | patch: "inside the dev app project" |
| 18 | code review: blind | ADR 9 Status not in ADR 18's pattern | low | ADR 18 keeps date and "Accepted" below | patch |
| 19 | code review: blind | External uptime monitor not weighed | low | alternatives list | patch: alternative added |
| 20 | code review: blind | Lost signal for a broken deploy unstated | low | deploy.sh waits for the API healthcheck | patch: consequence |
| 21 | code review: blind | "there is no Redis" vs ADR 6 | low | Redis never deployed | patch: "not deployed" |
| 22 | code review: blind | AD-15 binds alerting | low | spine:135 | patch |
| 23 | code review: blind | ADR names a person | low | no other ADR does | patch: impersonal |
| 24 | code review: blind | Issue #26 text not in the change set | false | drafted in the scratchpad, edited after merge with Vlad's ok | reject |
| 25 | code review: verification-gap | none | n/a | | n/a |

## Verification

**Commands:**
- `grep -rniw "telegram\|alertmanager\|tempo\|healthchecks" README.md README.uk.md docs/` -- expected: hits only in `docs/adr/0007-*`, `0009-*`, `0015-*`, `0023-*`.

**Manual checks:**
- Links in the new and amended ADRs and the README tables resolve.

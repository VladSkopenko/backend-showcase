---
title: 'Dashboards'
type: 'feature'
created: '2026-11-17'
status: 'in-progress'
baseline_commit: '64698094384cf8a6e03053e1b4fd2ef2c0467a87'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/SPEC.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/dashboards.md'
  - '{project-root}/_bmad_output/implementation-artifacts/spec-restaurant-simulation/patterns.md'
  - '{project-root}/docs/adr/0019-public-grafana-reads-dev.md'
  - '{project-root}/.claude/rules/backend.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The public Grafana opens on an empty welcome page: the dev simulation has data for every question a reviewer would ask, and nothing shows it.

**Approach:** The five dashboards of `dashboards.md`, written as JSON files in the repository and provisioned by Grafana from them (CAP-12). A visitor lands on a dashboard at once and moves between the five from any of them.

## Boundaries & Constraints

**Always:**
- Five dashboards, each with exactly the panels of `dashboards.md`: Bookings, Dishes, Checks, Visitors, Staff. Every panel reads the data source `restaurant-dev` and only what `grafana_reader` may read.
- Every dashboard has a time range and a location filter (all three locations by default, shown by address). Dashboards show times in `Asia/Tbilisi` whatever the browser's zone, and days and hours are cut in that zone in SQL.
- The time axis is the booking's start; on Staff it is the request's creation. The default range is the last 7 days to 14 days ahead, because most bookings made today start later: a range ending now would hide what the simulation is doing. On Staff, where nothing is created in the future, the default range ends now. "Pending requests now" ignores the range.
- A visit is a `CONFIRMED` booking. Dishes, checks, revenue, visitors, party sizes, the heatmap, lead time and occupancy count visits only; bookings per day shows confirmed and cancelled apart; the cancellation rate is cancelled over confirmed plus cancelled.
- A check is `quantity` times the dish's current price over the submitted pre-order items of a visit; per person divides by the party size. Lunch is a start from 12:00 to 14:30, dinner from 18:00 to 21:30; other starts are left out of the lunch and dinner panel.
- Occupancy is the booked table time of visits over the tables' open time, 10:00 to 23:00 on each day of the range.
- A request is a booking for more than 4 people. It was approved when `decided_by_id` is set and it is `CONFIRMED` or `CANCELLED` (cancelled later by the guest). A rejection without `decided_by_id` is automatic. A rejection with the same table and decision time as an approval was caused by the competitor. Approval rate is approved over approved plus the other staff rejections. Time to decision covers those staff decisions only. Requests per day is split by outcome, which is where competitor rejections show apart. The automatic share is over all decided requests.
- A regular is a visitor with at least a threshold of visits per 7 days of the selected range; the threshold is a dashboard variable, default 10. Repeat rate is the share of visitors with two or more visits. Top visitors show first and last name only.
- The start page of the public host shows the Bookings dashboard; each dashboard links to the other four.
- Claude writes the JSON; queries are tried on live dev through the public data source and the rendered dashboards are checked on screenshots. Vlad judges the look.
- Dashboards are provisioned from `deploy/platform/grafana/`, cannot be saved from the UI, and a changed dashboard file reaches Grafana without a restart.
- A test runs every panel and variable query against the migrated schema as `grafana_reader`, so a dashboard cannot use a column the role lacks or one a later migration removes.
- Compose and provisioning files are written one at a time with Vlad, every key checked against the docs.

**Never:** New columns, tables or grants; a new data source; alerts; panels beyond `dashboards.md`; Enterprise features; editing dashboards in the UI as the source of truth; `SET`, `ALTER` or any write through the public data source.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Start page | anonymous visitor opens the public host | the Bookings dashboard | N/A |
| Panels | each dashboard on live dev, default range | no panel shows an error; every panel whose data exists in the range shows it | N/A |
| Location filter | one location chosen | every panel query is narrowed by it | N/A |
| Empty range | a range with no bookings | no query error | N/A |
| Role | any panel or variable query run as `grafana_reader` | succeeds | a query needing an ungranted column fails the test |
| Changed file | a dashboard JSON changes on disk | Grafana shows the new version without a restart | N/A |
| UI edit | admin edits a provisioned dashboard | it cannot be saved | N/A |

</frozen-after-approval>

## Code Map

- `deploy/platform/grafana/dashboards/` -- new: `bookings.json`, `dishes.json`, `checks.json`, `visitors.json`, `staff.json`. Classic dashboard JSON (the model Grafana exports), uids `bookings`, `dishes`, `checks`, `visitors`, `staff`, a shared tag `restaurant` for the links, `"timezone": "Asia/Tbilisi"`, `"time": {"from": "now-7d", "to": "now+14d"}`, `"editable": false`.
- Every panel and variable names the data source as `{"type": "grafana-postgresql-datasource", "uid": "restaurant-dev"}` (`deploy/platform/grafana/provisioning/datasources/postgres.yaml`).
- `backend/migrations/versions/0021_add_grafana_reader_role.py` -- `READABLE_COLUMNS`: the only columns a query may touch. No `email`, no `preorder_items.note`, no `guests`.
- Schema: ids are `uuid`, times `timestamptz`; `bookings.status` is `CONFIRMED`, `CANCELLED`, `PENDING`, `REJECTED`; a cancellation's time is `updated_at`; `preorder_items.state` is `SUBMITTED` or `DRAFT` and items hang on `booking_participants.id`; `dishes.category` is `APPETIZER`, `MAIN_COURSE`, `DESSERT`, `price_cents` is the price; a location is shown by `locations.address`; tables belong to a location through `dining_tables.location_id`.
- `backend/tests/test_grafana_reader_migration.py`, `backend/tests/support/migrations.py` -- how a test applies `0021` as dev and runs under `SET LOCAL ROLE grafana_reader` inside the rolled-back transaction. Shared helpers live in `tests/support/`; test modules never import each other.
- Live data, read-only, as the role: `curl -s -X POST https://backend-showcase-grafana.duckdns.org/api/ds/query -H 'Content-Type: application/json' -d '{"queries":[{"refId":"A","datasource":{"uid":"restaurant-dev"},"rawSql":"SELECT 1","format":"table"}],"from":"now-7d","to":"now+14d"}'`. The same endpoint is the way to copy the readable rows into a throwaway database.
- Rendering check: a throwaway Grafana 13.2.6 (`docker run --rm`, `--tmpfs /var/lib/grafana:uid=472,gid=0,mode=700,exec`, anonymous access on, `GF_PLUGINS_PREINSTALL_DISABLED=true`) with a throwaway provider file kept outside the repository, next to a throwaway `postgres:18` on tmpfs; screenshots with `docker run --rm -v <dir>:/out zenika/alpine-chrome --no-sandbox --headless --disable-gpu --hide-scrollbars --window-size=1600,2400 --virtual-time-budget=25000 --screenshot=/out/x.png <url>`.
- Not part of the implementation hand-off: `deploy/platform/compose.yml`, `deploy/platform/grafana/provisioning/dashboards/` and the home-page setting. Vlad and the parent session write them.
- `_bmad_output/implementation-artifacts/deferred-work.md` -- settled here: competitor rejections on the staff dashboard, and dashboard files that change without a restart. The data source file still needs a restart to change.

## Tasks & Acceptance

**Execution:**
- [x] `backend/tests/test_grafana_dashboards.py` (helpers in `backend/tests/support/` if shared) -- new; the five files exist with their uids, the `restaurant-dev` data source, the zone, the default range, a location variable and the panel titles of `dashboards.md`; every panel query uses the location variable; every panel and variable query runs as `grafana_reader` with Grafana's macros and variables replaced, for the default range and for an empty one -- contract.
- [x] `deploy/platform/grafana/dashboards/*.json` -- the five dashboards -- content.
- [x] `deploy/platform/grafana/provisioning/dashboards/dashboards.yaml`, `deploy/platform/compose.yml` -- provider, mounts, the start page -- with Vlad.
- [x] `README.md`, `README.uk.md`, `docs/adr/0019-public-grafana-reads-dev.md` -- a link to the public Grafana and what the dashboards compute -- docs.

**Acceptance Criteria:**
- Given the full suite, when `uv run pytest` runs, then all pass.
- Given a throwaway Grafana 13.2.6 provisioned from the repository against a throwaway database holding a copy of the readable dev rows, when each dashboard is opened anonymously, then a screenshot shows every panel without an error.
- Given that throwaway Grafana, when a dashboard file changes on disk, then the dashboard shows the change within the provider's interval without a restart.
- Given the deploy, when a browser outside the tailnet opens `https://backend-showcase-grafana.duckdns.org`, then the Bookings dashboard shows live data and the other four open from its links.

## Implementation Notes

- 2026-11-17: spec review before implementation, checked on live dev by the parent session. Submitted pre-orders on cancelled bookings carry 31.5% of the money (2,738,500 of 8,686,900 cents), so checks count visits only. 497 of 896 confirmed bookings start after now, hence the default range into the future. Visitors' confirmed bookings run from 6 to 18 per week with nine at 10 or more, hence the default threshold. The role's session zone is UTC, so SQL cuts days in `Asia/Tbilisi` itself. Live cancellations are about 30% of bookings, twice the "one in seven" CAP-8 used to promise. Vlad decided not to tune the simulator to it: the dashboards show the data as it is, and the figure was dropped from CAP-8.
- 2026-11-17, implementation: the test (32 cases, failing before the dashboards existed) and the five JSON files were written by an implementation subagent from this spec; the provider file, the compose mounts and the start-page setting by the parent session with Vlad. The parent ran the full suite (709 passed) and the linters, and looked at the five screenshots: every panel renders with data and without an error.
- Choices made while building, for Vlad to judge on the live site: the two heat panels are tables with coloured cells, because Grafana's heatmap wants time on the x axis; top lists have 10 rows; "Regulars vs occasional" is two stat tiles; the regular threshold is a dropdown from 4 to 16; the average check is taken over visits with a submitted pre-order, and per person is the mean of check over party size per visit; occupancy clips the open time to the selected range; money is shown with `$`, as the frontend's `formatPrice` does; locations keep fixed colours; parties of 5 to 8 are one series; "Requests per day" has six outcomes, with "Lost to another request" at 0 on dev today; no auto-refresh.
- The start page was tried by the parent on a throwaway Grafana 13.2.6: with `default_home_dashboard_path` an anonymous visit to `/` renders the dashboard with its links, range and zone. Grafana serves it under the uid `default-home-dashboard`, so its link row lists all five dashboards.
- Reported by the implementation subagent and not re-run by the parent: on a throwaway Grafana provisioned from the repository's own provider and compose paths over a copy of the readable dev rows, a changed dashboard file showed after 5 to 29 seconds with no restart, saving as admin answered 400 "Cannot save provisioned dashboard", and each dashboard rendered with one location chosen and with an empty range. Headless Chromium needs `--shm-size=1g`, or about one load in five hangs.
- 2026-11-17: Vlad agreed to end Staff's default range at now, since its chart was two thirds empty. The links between dashboards keep the chosen range, so Staff opened from another dashboard still shows that dashboard's range.

## Spec Change Log

## Review Triage Log

## Verification

**Commands:**
- `cd backend && uv run pytest` -- expected: all pass
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run lint-imports` -- expected: clean

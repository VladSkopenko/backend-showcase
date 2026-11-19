# Roadmap

[README](../README.md)

The plan for the project and how it ended. The project runs on dev only and finishes after the logs
([ADR 24](adr/0024-the-project-ends-on-dev.md)). Ticked items are done and verified; the items that
were planned and dropped are listed at the end with the reason.

## Product vision

A restaurant app that ends at the pre-order. Guests register, browse the menu, book tables, invite
friends to the booking, pre-order food for the visit and ask an AI assistant. The restaurant
decides large-party requests, emails its decisions and shows its numbers in a public Grafana.

| Feature | What makes it interesting |
|---|---|
| Accounts | registration with email verification, login with rotating refresh tokens, Google sign-in |
| Menu | categories, dishes, prices, availability |
| Table booking | double booking is impossible at the database level: a PostgreSQL exclusion constraint on table and time range |
| Invites | friends join a booking through a link, also without an account |
| Pre-order | every participant keeps their own cart and submits it in parts; the owner sees the whole group |
| Large-party requests | 5 to 8 people send a request that does not hold the table; staff approve or reject, and a request still pending 2 hours before the start is rejected automatically |
| Decision emails | an email to every participant with an account when staff or the automatic rejection decide a request |
| AI assistant | a chat on the website with streamed answers, tools over the guest's data and the menu, and changes only after the person confirms a card; one daily budget for the whole system |
| Analytics | a public Grafana reads the dev database: bookings by hour, top dishes, average check, visitors, staff reaction time |
| Frontend | menu, booking, invites, pre-order and the assistant chat; a separate Next.js repository that reaches this API through its own server-side proxy |

### n8n as the traffic simulator

n8n plays the visitors and the waiter. On dev about 40 guest bots book tables, pre-order, cancel
and send large-party requests through the REST API with the patterns of a real restaurant, and a
waiter bot decides the requests; it runs on dev only, where it cannot take real guests' tables
([ADR 14](adr/0014-booking-simulator-on-dev.md)). Workflows are exported to
`n8n/workflows/` and versioned with the code.

### Out of scope

- Food orders as a state machine, a live order tracker and a kitchen screen.
- Payments, even in a sandbox: a real restaurant bills at the table. Invoices and reviews go with
  them.
- Roles for guests, staff and managers in the product (waiters live only in n8n), and menu
  management routes.
- Translations of the menu and the API.
- Live video from the kitchen. A media server would eat the free VM's bandwidth and CPU and adds
  little backend value.

## Stack

| Area | Choice |
|---|---|
| API | Python 3.14, FastAPI, Pydantic v2, uvicorn |
| Data | PostgreSQL, SQLAlchemy 2.0 async, Alembic |
| AI assistant | OpenAI through LangChain, answers streamed over Server-Sent Events, history and limits in PostgreSQL |
| Background jobs | periodic tasks inside the API process, one API process |
| Dependencies | uv with a lockfile |
| Code quality | ruff for lint and format, strict mypy, import-linter, SonarCloud |
| Tests | pytest, httpx2, a real PostgreSQL with savepoint rollback, coverage reported to SonarCloud |
| Containers | multi-stage Dockerfile for `linux/arm64`, non-root user, healthcheck; docker compose per layer |
| CI | GitHub Actions on every pull request: lint, types, import contracts, a migration round-trip, tests with a PostgreSQL service, SonarCloud with coverage |
| CD | build each tree once, Trivy scan, push to GHCR, deploy the digest to dev |
| Metrics | one Prometheus labelled by `env`; app, node and Postgres exporters |
| Dashboards | Grafana provisioned from the repo: technical metrics plus business analytics from PostgreSQL |
| Logs | VictoriaLogs, lighter than Loki, decided in an ADR; no traces or alerts ([ADR 23](adr/0023-observability-ends-with-logs.md)) |
| Automation | n8n workflows that simulate guests and a waiter on dev through the REST API |
| Private access | Tailscale for Prometheus, VictoriaLogs, n8n and CI deploys |
| Infrastructure | Terraform for the Oracle Cloud VM, network, firewall and data volume; cloud-init for the base OS; Caddy with automatic HTTPS |
| Frontend | Next.js in a separate repository, hosted on Vercel; see [ADR 10](adr/0010-frontend-in-a-separate-repository.md) |

## Phases

### Phase 0. Repository
- [x] README, agent rules and BMAD
- [x] `.gitignore` covering `CLAUDE.local.md` and `.env` files

Done when: the repo is public and the README explains what it shows.

### Phase 1. Minimal API
- [x] FastAPI app with `/health`, registration and login
- [x] Menu as the first read-only resource
- [x] PostgreSQL, SQLAlchemy models, first Alembic migration
- [x] docker compose for the local PostgreSQL
- [x] Tests for the endpoints against a real database

Done when: the API and the tests run locally against the compose PostgreSQL.

### Phase 2. Quality gates
- [x] GitHub Actions on every pull request: lint, types, import contracts, a migration round-trip, tests
- [x] SonarCloud analysis from CI with test coverage; CI and SonarCloud badges in the README

Done when: every pull request shows a red or green CI run and a SonarCloud quality gate.

### Phase 3. Containers and delivery
- [x] Terraform for the Oracle Cloud VM, network, firewall and data volume, with state in Object Storage; cloud-init for the base OS
- [x] Deploy access only through Tailscale, port 22 closed, a forced-command entrypoint that deploys only commits from the environment's branch
- [x] Multi-stage Dockerfile with a small runtime image and a non-root user
- [x] Build on an arm64 runner, scan with Trivy, push to GHCR tagged with the tree hash and the commit sha
- [x] An app compose project for dev on the VM, with its own database and secrets
- [x] Deploy runs migrations and waits for the API's healthcheck

Done when: a merge to `main` reaches dev without manual steps.

### Phase 4. Observability and platform
Tracked step by step in [issue #26](https://github.com/VladSkopenko/backend-showcase/issues/26),
following [ADR 15](adr/0015-platform-as-code.md).
- [x] `/metrics` with request rate, errors and latency per endpoint
- [x] Platform stack deployed separately from the app stacks
- [x] Prometheus scraping the dev API and the host's node exporter
- [ ] Postgres exporter for the dev database
- [x] Grafana dashboards provisioned from the repo, with an environment selector
- [ ] Structured JSON logs in VictoriaLogs
- [x] n8n in the platform stack; Prometheus and n8n reachable only through Tailscale

The phase ends with logs: no traces and no alerting ([ADR 23](adr/0023-observability-ends-with-logs.md)).

Done when: a visitor sees the dev API's metrics and the server's health on the public Grafana, and the logs land in VictoriaLogs.

### Phase 5. Infrastructure as code
- [x] The data on a block volume separate from the VM, so a replaced server reattaches it ([ADR 8](adr/0008-terraform-and-immutable-server.md))
- [x] Caddy with automatic HTTPS on DuckDNS subdomains for the dev API and the public Grafana
- [x] Secrets only in GitHub secrets, never in the repo

Done when: the infrastructure is described in Terraform and cloud-init, and no secret lives in the repo.

### Phase 6. Product
Each feature starts from its own BMAD spec.
- [x] Table booking with the exclusion constraint
- [x] Invites: friends join a booking through a link, also without an account
- [x] Pre-order: every participant's own cart, submitted in parts
- [x] Large-party requests decided by staff, rejected automatically 2 hours before the start
- [x] Decision emails (the in-app notifications were removed later, ADR 21)
- [x] n8n simulator on dev: guest bots book, pre-order, cancel and send requests; a waiter bot decides them
- [x] Business dashboards in a public Grafana on dev data
- [x] Group pre-order: the booking owner sees every participant's submitted parts
- [x] Cleanup of expired refresh tokens and old verification codes
- [x] AI assistant: a chat with streamed answers and read tools, under one daily budget for the system
- [x] AI assistant actions: booking and cart changes through cards the person confirms
- [x] Frontend in its own repository: menu, booking, invites, pre-order and the assistant chat

Done when: a guest books a table, invites friends, everyone pre-orders and the owner sees the
group's pre-order; the assistant answers about the menu and books a table after the guest
confirms; the public Grafana shows the restaurant's numbers.

## Dropped

Planned once and dropped when the project settled on dev
([ADR 24](adr/0024-the-project-ends-on-dev.md)):

- Staging and production, and the promotion of one image from `main` to `rc` to `prod`
- Rolling migrations back on a failed deploy ([ADR 5](adr/0005-migration-rollback-with-alembic.md))
- Redis ([ADR 6](adr/0006-data-stack-per-environment.md))
- A nightly `pg_dump` with a tested restore
- k6 load tests and their numbers
- A Makefile, pre-commit hooks, a coverage threshold, branch protection and a Terraform-managed
  tailnet policy
- k3s with Helm instead of docker compose

## What a reviewer sees

- CI and SonarCloud badges at the top of the README
- Live URLs with HTTPS: the dev API, its Swagger and the public Grafana
- An architecture diagram and the decision records

# Roadmap

[README](../README.md)

The full plan for the project. The README lists what is built today; this page keeps the target
product, the target stack and the phases. Ticked items are done and verified.

## Product vision

A restaurant app. Guests register, browse the menu, book tables, order food and follow the order
live. The restaurant gets invoices, reviews, notifications and analytics.

| Feature | What makes it interesting |
|---|---|
| Accounts | registration and login, roles for guests, staff and managers |
| Menu | categories, dishes, prices, availability |
| Table booking | double booking is impossible at the database level: a PostgreSQL exclusion constraint on table and time range |
| Food orders | an order is a state machine: placed, accepted, cooking, ready, completed or cancelled |
| Live order tracker | the guest sees every stage with an ETA countdown and the kitchen screen sees new orders instantly, over WebSocket with Redis pub/sub so it works across workers |
| Payments | a payment provider sandbox with signed webhooks and idempotency keys, so a repeated webhook never charges twice |
| Invoices | PDF with VAT rendered by a background job and stored in Object Storage |
| Reviews | on a dish, a visit or a booking: one table with three foreign keys and a CHECK that exactly one is set |
| Analytics | Grafana reads PostgreSQL directly: revenue, popular dishes, ratings, no-shows |
| Frontend | menu and booking, order tracker, kitchen screen; a separate Next.js repository that reaches this API through its own server-side proxy |

### n8n as the traffic simulator

n8n plays the visitors, so every environment shows a live flow: it books random tables through the
REST API and moves demo orders through the kitchen
([ADR 9](adr/0009-alerting-from-outside-the-vm.md)). Workflows are exported to `n8n/workflows/` and
versioned with the code.

### Out of scope

- Live video from the kitchen. A media server would eat the free VM's bandwidth and CPU and adds
  little backend value; the live kitchen screen covers the demo.

## Planned stack

| Area | Choice |
|---|---|
| API | Python 3.14, FastAPI, Pydantic v2, uvicorn |
| Data | PostgreSQL, SQLAlchemy 2.0 async, Alembic |
| Real-time | WebSocket, Redis pub/sub |
| Background jobs | Celery or Taskiq on Redis, decided in an ADR |
| Dependencies | uv with a lockfile |
| Code quality | ruff for lint and format, mypy |
| Tests | pytest, pytest-asyncio, httpx2, testcontainers, coverage with a minimum threshold |
| Git hooks | pre-commit: ruff and mypy on commit, pytest on pre-push |
| Containers | multi-stage Dockerfile for `linux/arm64`, non-root user, healthcheck; docker compose per layer and environment |
| CI | GitHub Actions on every pull request: lint, types, tests with Postgres and Redis services, coverage |
| CD | build each tree once, Trivy scan, push to GHCR, promote the same digest through dev, staging and production |
| Metrics | one Prometheus for all environments, labelled by `env`; app, node, Postgres and Redis exporters |
| Dashboards | Grafana provisioned from the repo: technical metrics plus business analytics from PostgreSQL |
| Logs and traces | VictoriaLogs, lighter than Loki, decided in an ADR; OpenTelemetry traces in Tempo |
| Alerts | Alertmanager to a Telegram bot, Watchdog to healthchecks.io as a dead-man switch |
| Automation | n8n workflows that simulate visitors: random table bookings through the REST API |
| Private access | Tailscale for Prometheus, VictoriaLogs, n8n and CI deploys |
| Infrastructure | Terraform for the Oracle Cloud VM, network, firewall and data volume; cloud-init for the base OS; Caddy with automatic HTTPS |
| Frontend | Next.js in a separate repository, hosted on Vercel; see [ADR 10](adr/0010-frontend-in-a-separate-repository.md) |
| Load testing | k6 with thresholds, results published in this README |
| Stretch | k3s with Helm instead of docker compose |

## Phases

### Phase 0. Repository
- [x] README, agent rules and BMAD
- [ ] License, `.gitignore` covering `CLAUDE.local.md` and `.env` files, `.editorconfig`
- [ ] Makefile with `up`, `down`, `test`, `lint`
- [ ] Branches `main`, `rc`, `prod` with protection rules
- [ ] `docs/adr/0001-record-architecture-decisions.md`

Done when: the repo is public and the README explains what is coming.

### Phase 1. Minimal API
- [x] FastAPI app with `/health`, registration and login
- [ ] Menu as the first CRUD resource
- [x] PostgreSQL, SQLAlchemy models, first Alembic migration
- [ ] docker compose for local development: app, Postgres, Redis
- [x] Tests for the endpoints against a real database

Done when: `make up` starts everything and `make test` passes locally.

### Phase 2. Quality gates
- [ ] pre-commit hooks: ruff and mypy on commit, tests on pre-push
- [ ] GitHub Actions on every pull request: lint, types, tests, coverage
- [ ] Coverage threshold and a CI badge in this README

Done when: a pull request with a failing test cannot be merged.

### Phase 3. Containers and delivery
- [x] Terraform for the Oracle Cloud VM, network, firewall and data volume, with state in Object Storage; cloud-init for the base OS
- [x] Deploy access only through Tailscale, port 22 closed, a forced-command entrypoint that deploys only commits from the environment's branch
- [x] Multi-stage Dockerfile with a small runtime image and a non-root user
- [ ] Build on an arm64 runner, scan with Trivy, push to GHCR tagged with the tree hash and the commit sha
- [ ] Three app compose projects on the VM: dev, staging and production, each with its own database and secrets
- [ ] Deploy runs migrations, gates on `/health`, and on failure downgrades the migrations and rolls back to the previous digest
- [ ] Promotion by pull requests `main` to `rc` and `rc` to `prod`, with manual approval for production; hotfixes through `rc`

Done when: a merge to `main` reaches dev without manual steps, and the same image reaches production
after two pull requests and one approval.

### Phase 4. Observability and platform
- [ ] `/metrics` with request rate, errors and latency per endpoint
- [ ] Platform stack deployed separately from the app stacks
- [ ] Prometheus scraping all three environments and the exporters
- [ ] Grafana dashboards provisioned from the repo, with an environment selector
- [ ] Structured JSON logs in VictoriaLogs, traces in Tempo, linked from Grafana
- [ ] Alert rules with Alertmanager sending to Telegram, a dead-man switch on healthchecks.io, an alert on orders stuck in `placed`
- [ ] n8n in the platform stack; Prometheus, VictoriaLogs and n8n reachable only through Tailscale

Done when: a broken production deploy raises an alert in Telegram within minutes.

### Phase 5. Infrastructure as code
- [ ] Server replacement with `terraform apply -replace`, data reattached from the block volume
- [ ] Tailnet policy managed by Terraform
- [ ] Caddy in front of all three environments with automatic HTTPS on DuckDNS subdomains
- [ ] Nightly `pg_dump` of production to Object Storage, with one tested restore
- [ ] Secrets only in GitHub environments, never in the repo

Done when: the server can be destroyed and recreated with one command, and production data survives it.

### Phase 6. Performance
- [ ] k6 scenario for booking and ordering with thresholds
- [ ] Load test run in CI on demand against staging, results and Grafana screenshots in this README

Done when: the README states the measured throughput and p95 latency.

### Phase 7. Product
Each feature starts from its own BMAD spec.
- [ ] Table booking with the exclusion constraint
- [ ] Orders as a state machine, with the live tracker and the kitchen screen over WebSocket
- [ ] Payments in a provider sandbox with signed, idempotent webhooks
- [ ] Invoice PDFs in a background job
- [ ] Reviews on dishes, visits and bookings
- [ ] n8n workflow that books random tables through the REST API, so every environment shows a live booking flow
- [ ] Business dashboards in Grafana
- [ ] Frontend in its own repository: menu and booking, order tracker, kitchen screen

Done when: a guest books, orders, pays, follows the order live, gets an invoice and leaves a review,
and the manager sees all of it in Grafana.

## What a reviewer should eventually see

- A green CI badge and a coverage badge at the top of this README
- Three live URLs with HTTPS: dev, staging and production
- A GIF of the live order tracker and the kitchen screen, with a link to the frontend repository
- An architecture diagram and the decision records
- Grafana screenshots and load test numbers

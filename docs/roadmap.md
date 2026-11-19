# Roadmap

[README](../README.md)

The full plan for the project. The README lists what is built today; this page keeps the target
product, the target stack and the phases. Ticked items are done and verified.

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
waiter bot decides the requests; it never runs on staging or prod, where it would take real
guests' tables ([ADR 14](adr/0014-booking-simulator-on-dev.md)). Workflows are exported to
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

## Planned stack

| Area | Choice |
|---|---|
| API | Python 3.14, FastAPI, Pydantic v2, uvicorn |
| Data | PostgreSQL, SQLAlchemy 2.0 async, Alembic |
| AI assistant | OpenAI through LangChain, answers streamed over Server-Sent Events, history and limits in PostgreSQL |
| Background jobs | periodic tasks inside the API process, one API process per environment |
| Dependencies | uv with a lockfile |
| Code quality | ruff for lint and format, mypy |
| Tests | pytest, pytest-asyncio, httpx2, testcontainers, coverage with a minimum threshold |
| Git hooks | pre-commit: ruff and mypy on commit, pytest on pre-push |
| Containers | multi-stage Dockerfile for `linux/arm64`, non-root user, healthcheck; docker compose per layer and environment |
| CI | GitHub Actions on every pull request: lint, types, tests with Postgres and Redis services, coverage |
| CD | build each tree once, Trivy scan, push to GHCR, promote the same digest through dev, staging and production |
| Metrics | one Prometheus for all environments, labelled by `env`; app, node and Postgres exporters |
| Dashboards | Grafana provisioned from the repo: technical metrics plus business analytics from PostgreSQL |
| Logs | VictoriaLogs, lighter than Loki, decided in an ADR; no traces or alerts ([ADR 23](adr/0023-observability-ends-with-logs.md)) |
| Automation | n8n workflows that simulate guests and a waiter on dev through the REST API |
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
- [x] Menu as the first read-only resource
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
Tracked step by step in [issue #26](https://github.com/VladSkopenko/backend-showcase/issues/26),
following [ADR 15](adr/0015-platform-as-code.md).
- [x] `/metrics` with request rate, errors and latency per endpoint
- [x] Platform stack deployed separately from the app stacks
- [ ] Prometheus scraping dev with node and Postgres exporters
- [ ] Staging and prod targets with their go-live (Phase 3, [ADR 22](adr/0022-prometheus-scrapes-dev.md))
- [x] Grafana dashboards provisioned from the repo, with an environment selector
- [ ] Structured JSON logs in VictoriaLogs
- [ ] n8n in the platform stack; Prometheus, VictoriaLogs and n8n reachable only through Tailscale

The phase ends with logs: no traces and no alerting ([ADR 23](adr/0023-observability-ends-with-logs.md)).

Done when: a visitor sees the dev API's metrics and the server's health on the public Grafana, and the logs land in VictoriaLogs. The staging and prod targets follow their go-live in Phase 3.

### Phase 5. Infrastructure as code
- [ ] Server replacement with `terraform apply -replace`, data reattached from the block volume
- [ ] Tailnet policy managed by Terraform
- [ ] Caddy in front of all three environments with automatic HTTPS on DuckDNS subdomains
- [ ] Nightly `pg_dump` of production to Object Storage, with one tested restore
- [ ] Secrets only in GitHub environments, never in the repo

Done when: the server can be destroyed and recreated with one command, and production data survives it.

### Phase 6. Performance
- [ ] k6 scenario for booking and pre-order with thresholds
- [ ] Load test run in CI on demand against staging, results and Grafana screenshots in this README

Done when: the README states the measured throughput and p95 latency.

### Phase 7. Product
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
- [ ] Frontend in its own repository: menu, booking, invites, pre-order and the assistant chat

Done when: a guest books a table, invites friends, everyone pre-orders and the owner sees the
group's pre-order; the assistant answers about the menu and books a table after the guest
confirms; the public Grafana shows the restaurant's numbers.

## What a reviewer should eventually see

- A green CI badge and a coverage badge at the top of this README
- Three live URLs with HTTPS: dev, staging and production
- A GIF of booking a table through the assistant chat, with a link to the frontend repository
- An architecture diagram and the decision records
- Grafana screenshots and load test numbers

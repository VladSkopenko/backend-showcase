# Backend Showcase

Working title.

An open-source REST API backend for a restaurant, built to show production-grade engineering end to
end: tests, CI/CD across three environments, containers, observability, automation and
infrastructure as code, all running for $0.

## Ground rules

- Built by hand. Every file can be explained line by line in a technical interview.
- Public datasets and public APIs only.
- Each phase ends green in CI and with this README updated, including a screenshot where it helps.
- Small commits, pull requests only, branch protection on `main`, `rc` and `prod`.
- Branches: `feature/*` and `fix/*` merge into `main`, `hotfix/*` into `rc`.
- Every non-obvious choice gets a short decision record in `docs/adr/`.

## Working with AI agents

This repo is built with Claude Code and the BMAD method, and the setup is part of the showcase.

- `CLAUDE.md` and `.claude/rules/` describe how the agent works here: language and tone, safety,
  and a spec-first, tests-first workflow. Backend rules load only when backend files are touched.
- `.claude/settings.json` turns the hard rules into guardrails: git state changes, deletions,
  migrations and formatters always ask first, and secret files are never read.
- `_bmad_output/` keeps the specs and stories that every feature starts from.
- Infrastructure is written by hand. The agent explains and reviews it.

## Product

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
| Frontend | minimal: menu and booking, order tracker, kitchen screen |

### n8n as the integration layer

The backend owns business logic and data. It publishes domain events such as `booking.created`,
`order.status_changed` and `review.created` through a transactional outbox to n8n webhooks, and n8n
handles everything around them:

- booking confirmations and reminders in Telegram;
- a morning digest for the manager: revenue, bookings, top dishes;
- review triage: an LLM sets sentiment and topic through the API, negative reviews alert the
  manager, and a weekly summary lists the best and worst dishes;
- a Telegram booking agent that understands "a table for four tomorrow at 19:00", with this REST API
  as its tools.

Workflows are exported to `n8n/workflows/` and versioned with the code.

### Out of scope

- Live video from the kitchen. A media server would eat the free VM's bandwidth and CPU and adds
  little backend value; the live kitchen screen covers the demo.

## Environments

| Branch | Environment | Deploy |
|---|---|---|
| `main` | dev | automatically on every merge |
| `rc` | staging | automatically on a merge from `main` or a `hotfix/*` branch |
| `prod` | production | on a merge from `rc`, after a manual approval in GitHub Environments |

Images are identified by the git tree hash, and each tree is built at most once. The same image moves
from dev to staging to production by digest, and nothing is rebuilt on promotion. A hotfix merged into
`rc` is built once there and cherry-picked back into `main`; a check on the next `main` to `rc` pull
request catches a forgotten cherry-pick. See [ADR 4](docs/adr/0004-image-identity-and-promotion.md).

One free VM runs two layers. The platform stack is deployed once: Caddy, Prometheus, Grafana,
VictoriaLogs, Tempo, Alertmanager and n8n. The app stack is deployed per environment by the
pipeline, with its own compose project, network, database and secrets, so app deploys never restart
the platform. Only the API and Grafana are public; the other UIs are reachable through Tailscale, and
CI deploys over the tailnet with SSH closed to the internet. See
[ADR 2](docs/adr/0002-ci-access-through-tailscale.md), [ADR 3](docs/adr/0003-deploy-entrypoint-verifies-commit.md)
and [ADR 7](docs/adr/0007-single-vm-platform-and-app-stacks.md).

## Running it for $0

| Need | Free option | Limits to remember |
|---|---|---|
| Server | Oracle Cloud Always Free, one Ampere A1 VM | 2 OCPUs and 12 GB of RAM in total for Arm, 200 GB of block storage |
| CI/CD | GitHub Actions in a public repository | standard runners are free, arm64 included |
| Container registry | GitHub Container Registry | free for public images |
| Domains and HTTPS | DuckDNS subdomains, Caddy with Let's Encrypt | 5 subdomains per DuckDNS account |
| Terraform state and backups | OCI Object Storage | 20 GB in total |
| Private access | Tailscale | free personal plan |
| Alerts | Telegram bot | none |
| Dead-man switch | healthchecks.io | free plan |

Oracle caveats:
- Signup asks for a payment card for verification. Always Free resources stay free in the home region.
- The home region is chosen at signup and cannot be changed. Arm capacity in popular regions can be
  short, and the console then reports "out of host capacity".
- Oracle reclaims instances that look idle for 7 days: 95th-percentile CPU, network and memory all
  under 20%. The full stack keeps memory well above that, but watch it in Grafana.
- The VM is Arm, so images are built for `linux/arm64` on GitHub's arm64 runners.

## Planned stack

| Area | Choice |
|---|---|
| API | Python 3.14, FastAPI, Pydantic v2, uvicorn |
| Data | PostgreSQL, SQLAlchemy 2.0 async, Alembic |
| Real-time | WebSocket, Redis pub/sub |
| Background jobs | Celery or Taskiq on Redis, decided in an ADR |
| Dependencies | uv with a lockfile |
| Code quality | ruff for lint and format, mypy |
| Tests | pytest, pytest-asyncio, httpx, testcontainers, coverage with a minimum threshold |
| Git hooks | pre-commit: ruff and mypy on commit, pytest on pre-push |
| Containers | multi-stage Dockerfile for `linux/arm64`, non-root user, healthcheck; docker compose per layer and environment |
| CI | GitHub Actions on every pull request: lint, types, tests with Postgres and Redis services, coverage |
| CD | build each tree once, Trivy scan, push to GHCR, promote the same digest through dev, staging and production |
| Metrics | one Prometheus for all environments, labelled by `env`; app, node, Postgres and Redis exporters |
| Dashboards | Grafana provisioned from the repo: technical metrics plus business analytics from PostgreSQL |
| Logs and traces | VictoriaLogs, lighter than Loki, decided in an ADR; OpenTelemetry traces in Tempo |
| Alerts | Alertmanager to a Telegram bot, Watchdog to healthchecks.io as a dead-man switch |
| Automation | n8n workflows fed by backend events through a transactional outbox |
| AI | LLM review triage and a Telegram booking agent in n8n |
| Private access | Tailscale for Prometheus, VictoriaLogs, n8n and CI deploys |
| Infrastructure | Terraform for the Oracle Cloud VM, network, firewall and data volume; cloud-init for the base OS; Caddy with automatic HTTPS |
| Frontend | minimal pages, framework decided in an ADR |
| Load testing | k6 with thresholds, results published in this README |
| Stretch | k3s with Helm instead of docker compose |

## Roadmap

### Phase 0. Repository
- [x] README, agent rules and BMAD
- [ ] License, `.gitignore` covering `CLAUDE.local.md` and `.env` files, `.editorconfig`
- [ ] Makefile with `up`, `down`, `test`, `lint`
- [ ] Branches `main`, `rc`, `prod` with protection rules
- [ ] `docs/adr/0001-record-architecture-decisions.md`

Done when: the repo is public and the README explains what is coming.

### Phase 1. Minimal API
- [ ] FastAPI app with `/health`, registration and login
- [ ] Menu as the first CRUD resource
- [ ] PostgreSQL, SQLAlchemy models, first Alembic migration
- [ ] docker compose for local development: app, Postgres, Redis
- [ ] Tests for the endpoints against a real database

Done when: `make up` starts everything and `make test` passes locally.

### Phase 2. Quality gates
- [ ] pre-commit hooks: ruff and mypy on commit, tests on pre-push
- [ ] GitHub Actions on every pull request: lint, types, tests, coverage
- [ ] Coverage threshold and a CI badge in this README

Done when: a pull request with a failing test cannot be merged.

### Phase 3. Containers and delivery
- [ ] Terraform for the Oracle Cloud VM, network, firewall and data volume, with state in Object Storage; cloud-init for the base OS
- [ ] Deploy access only through Tailscale, port 22 closed, a forced-command entrypoint that deploys only commits from the environment's branch
- [ ] Multi-stage Dockerfile with a small runtime image and a non-root user
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
- [ ] Domain events through an outbox to n8n: confirmations, reminders, morning digest, review triage
- [ ] Telegram booking agent in n8n on top of the REST API
- [ ] Business dashboards in Grafana
- [ ] Minimal frontend: menu and booking, order tracker, kitchen screen

Done when: a guest books, orders, pays, follows the order live, gets an invoice and leaves a review,
and the manager sees all of it in Grafana and Telegram.

## Planned layout

```
.
├── backend/
│   ├── app/             # FastAPI application
│   ├── migrations/      # Alembic
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/            # menu and booking, order tracker, kitchen screen
├── n8n/workflows/       # exported n8n workflows
├── deploy/
│   ├── platform/        # Caddy, Prometheus, Grafana, VictoriaLogs, Tempo, Alertmanager, n8n
│   ├── app/             # docker compose per environment
│   └── terraform/
├── loadtests/           # k6 scenarios
├── docs/
│   ├── adr/
│   └── architecture.md  # Mermaid diagram
├── .github/workflows/
├── .pre-commit-config.yaml
└── Makefile
```

## What a reviewer should see

- A green CI badge and a coverage badge at the top of this README
- Three live URLs with HTTPS: dev, staging and production
- A GIF of the live order tracker and the kitchen screen
- An architecture diagram and the decision records
- Grafana screenshots and load test numbers


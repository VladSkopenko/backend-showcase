# 24. The project ends on dev

Date: 2026-11-20

## Status

Accepted. Supersedes [ADR 5](0005-migration-rollback-with-alembic.md). Amends
[ADR 4](0004-image-identity-and-promotion.md), [ADR 6](0006-data-stack-per-environment.md),
[ADR 7](0007-single-vm-platform-and-app-stacks.md), [ADR 22](0022-prometheus-scrapes-dev.md) and
[ADR 23](0023-observability-ends-with-logs.md), as listed below.

## Context

The plan was three environments on one VM: dev, staging and production, the same image promoted by
digest through pull requests from `main` to `rc` and from `rc` to `prod`
([ADR 4](0004-image-identity-and-promotion.md)), each with its own PostgreSQL and Redis
([ADR 6](0006-data-stack-per-environment.md)), a deploy that rolls the migrations back when the new
version fails ([ADR 5](0005-migration-rollback-with-alembic.md)), a nightly `pg_dump` of production
and k6 load tests against staging.

What exists is dev. Every merge to `main` builds the image once, scans it and deploys it to dev by
digest; the platform stack runs Prometheus, the public Grafana and n8n. The `rc` and `prod`
branches and their domains were created but never deployed, Redis was never deployed, the deploy
migrates forward only, and there is no backup job. With the product finished at the pre-order and
observability ending with logs ([ADR 23](0023-observability-ends-with-logs.md)), the project is
finished after the logs. Reviewers read every planned item that is not built as a gap, so the plans
must not outlive the decision.

## Decision

- **One environment.** The project runs dev only, with its own app compose project and PostgreSQL.
- **Dropped:** staging and production and the promotion from `main` to `rc` to `prod`; rolling
  migrations back on a failed deploy; Redis; the nightly `pg_dump` and its tested restore; k6 load
  tests; a Makefile, pre-commit hooks, a coverage threshold and a Terraform-managed tailnet policy.
- **Kept:** the image built once per git tree, scanned with Trivy, pushed to GHCR and deployed to dev
  by digest; Terraform for the VM, network, data volume and media bucket; deploys only through
  Tailscale; Prometheus, node_exporter, the postgres_exporter for dev and the public Grafana; logs in
  VictoriaLogs as the last step.
- **ADR 4 amended.** Images keep the tree-hash identity and reach dev by digest; there is no
  promotion to further environments.
- **ADR 5 superseded.** A deploy runs `alembic upgrade head` and starts the API behind its
  healthcheck. A failed migration or start is fixed forward with a new commit.
- **ADR 6 amended.** One app project, dev, with its own PostgreSQL; no Redis.
- **ADR 7 amended.** One app stack beside the platform stack.
- **ADR 22 and ADR 23 amended.** There are no staging or production targets to add.

## Alternatives considered

- **Start staging and production anyway.** Two more app stacks on the free VM's memory for
  environments with no users and no traffic of their own; they would show the same pipeline twice
  more.
- **Keep the plans in the roadmap as future work.** The project is finished; open items would stay
  open and be read as missing.

## Consequences

- The README and the roadmap describe only what is built; the dropped items are listed in the
  roadmap with this ADR as the reason.
- The `rc` and `prod` branches stay on GitHub unused.
- Dev has no backups. Its data comes from reference-data migrations and the n8n simulator, so losing
  it loses nothing real; a data volume separate from the VM keeps it across a server replacement
  ([ADR 8](0008-terraform-and-immutable-server.md)).

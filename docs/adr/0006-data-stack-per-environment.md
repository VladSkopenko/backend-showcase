# 6. Each environment runs its own PostgreSQL and Redis

Date: 2026-10-28

## Status

Accepted

## Context

Three environments share one VM with 2 OCPUs and 12 GB of RAM. Production is a public demo that any
visitor can walk through, so a dev deploy or experiment must never touch it. All three can either share
one PostgreSQL cluster or each run their own.

## Decision

- Each `app-<env>` compose project runs its own PostgreSQL and Redis.
- All environments use one compose file. Only `.env` differs.
- All state, for apps and the platform alike, uses bind mounts under `/srv/data/<env|platform>/` on a
  separate block volume that Terraform protects with `prevent_destroy`. Docker named volumes are never
  used for state.
- Every container sets `mem_limit`. PostgreSQL runs with `shared_buffers` around 128 MB.
- The `app-prod` project dumps production nightly to OCI Object Storage, and one restore is tested.

## Alternatives considered

- **One shared cluster with three databases.** It saves a few hundred megabytes, but it would live in
  the platform stack. Every environment would then depend on the platform, and a PostgreSQL upgrade
  would hit all three at once.

## Consequences

- A deploy, a rollback or a PostgreSQL upgrade in one environment cannot affect the others.
- Three PostgreSQL and three Redis instances fit the memory budget only with explicit limits.
- Replacing the VM keeps all data, because the block volume is reattached.

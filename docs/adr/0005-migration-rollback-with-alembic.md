# 5. Failed deploys roll back migrations with Alembic

Date: 2026-10-28

## Status

Accepted

## Context

A deploy runs migrations and then gates on `/health`. If the gate fails, the previous image comes back.
That image does not know the new schema, so the schema has to roll back as well.

## Decision

- `deploy.sh` records `alembic current`, runs `alembic upgrade head` with the new image, starts the new
  image and gates on `/health`.
- If the gate fails, it runs `alembic downgrade <recorded revision>` with the **new** image, because the
  old image does not contain the new migration files. Then it starts the previous digest.
- A migration that fails rolls back inside its own PostgreSQL transaction, and the running container is
  left untouched.
- Every migration has a working `downgrade()`. CI checks this on an empty database: `upgrade head`, then
  `downgrade base`, then `upgrade head`.
- Convention: a migration never drops or moves data in the same release as the code change that stops
  using it. That cleanup ships in a later release.

## Alternatives considered

- **Expand/contract only, no downgrades.** The safest option, but it doubles the steps for every schema
  change. That is too much ceremony for this project.
- **A pg_dump before every production migration.** It only protects against destructive upgrades, and
  the convention above rules those out at no cost.

## Consequences

- Rollback happens within seconds of a deploy, so columns that were just added are still empty when
  they are dropped again.
- `docker compose up` sends traffic to the new container before the health verdict. A write in that
  short window can be lost on rollback. This is accepted for a demo without real load. Blue-green
  deploys would remove the window.
- The data-safety convention depends on code review. Nothing enforces it mechanically.

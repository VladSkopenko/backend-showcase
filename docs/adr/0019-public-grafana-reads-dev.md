# 19. Public Grafana reads the dev database

Date: 2026-11-17

## Status

Accepted. Amends [ADR 7](0007-single-vm-platform-and-app-stacks.md) and architecture decision
AD-13: Grafana reads dev, not production, and every environment's PostgreSQL joins an analytics
network of its own. Amended 2026-11-17: what Grafana itself offers an anonymous visitor is
trimmed, and the platform deploy reports whether the data source can log in.

## Context

[ADR 7](0007-single-vm-platform-and-app-stacks.md) planned a public Grafana that reads production
PostgreSQL through a read-only role on one `analytics` network. The data worth showing lives
elsewhere: the restaurant simulation runs on dev only ([ADR 14](0014-booking-simulator-on-dev.md)),
while staging and production hold almost nothing and, later, real guests.

The dashboards must open without an account. In Grafana that is anonymous access with the Viewer
role, and a Viewer "can issue any possible query to a data source, not just queries that exist on
dashboards" ([Grafana docs](https://grafana.com/docs/grafana/latest/administration/data-source-management/));
restricting that needs Grafana Enterprise. So whatever the data source's database user may do,
anyone on the internet may do.

## Decision

- **Grafana reads dev.** It runs in the platform stack ([ADR 15](0015-platform-as-code.md)), is
  public at `backend-showcase-grafana.duckdns.org` through Caddy with anonymous Viewer, and has one
  PostgreSQL data source: the dev database. Staging and production get no role and no data source.
- **The database role is the security boundary.** Migration `0021` creates `grafana_reader` only
  when `APP_ENVIRONMENT` is `dev`, under the same gate as the bots of ADR 14. Every grant is a list
  of columns, never a whole table, so a new table or column stays invisible until a migration
  grants it. The role reads `bookings` (requests are its rows), `booking_participants`,
  `dining_tables`, `locations` and `dishes` in full, `preorder_items` without the free-text
  `note`, and from `users` only `id`, `first_name` and `last_name`. It reads no emails, password
  hashes, tokens, invite codes, guests, notifications or OAuth accounts, and writes nothing.
- **Names are public on purpose.** First and last names of every dev user are readable, real
  people who register on dev included: a visitor may find themselves in the statistics. Names are
  the only personal data the role sees.
- **The password is a public verifier.** The role logs in with a random 64-character password.
  `deploy/platform/secrets.sh` generates it, stores it in the GitHub Environment `platform` and
  prints its SCRAM-SHA-256 verifier, which is committed in the migration, as the bot password hash
  is in ADR 14. The application gets no new setting or secret.
- **Hard limits and soft defaults.** The role cannot change its grants, its connection limit of 5
  or its `temp_file_limit`. `statement_timeout` (5 s) and `default_transaction_read_only` are
  defaults: they keep dashboards and mistakes cheap, but a session can lift them with `SET`, and
  the role can remove them for every later session with `ALTER ROLE`.
- **Filling the disk is closed in the dev database.** Dev shares its data volume with production.
  With the read-only default lifted, any role may create temporary tables and large objects, so
  on dev the migration revokes `TEMPORARY` on the application database and `EXECUTE` on
  `lo_creat`, `lo_create` and `lo_from_bytea` from `PUBLIC`. The application connects as the owner
  and is not affected.
- **Grafana's own anonymous surface is trimmed.** Its `/metrics` endpoint is off, because Caddy
  would publish it with the exact version. Caddy answers 403 on `/api/short-urls`, because an
  anonymous Viewer may create short links and each is a row in Grafana's database that never
  expires. Plugin preinstall is off, so a start downloads nothing unpinned; the data source
  plugins bundled in the image remain. The admin's session cookie is `Secure`.
- **The deploy reports the data source, and does not depend on it.** Grafana's healthcheck passes
  without the dev database, so after `up --wait` the platform deploy asks Grafana for the data
  source's health and prints `ok` or `unreachable` in the job summary. It never fails the deploy:
  the platform must come up when dev is down. That line is the only automatic sign of a wrong
  password or of a role locked out by a visitor.
- **An analytics network per environment.** Each environment's PostgreSQL joins an internal
  network `analytics-<env>`, named from `APP_ENV` in the one app compose file
  ([ADR 6](0006-data-stack-per-environment.md)). Grafana joins `edge`, where Caddy reaches it, and
  of the analytics networks only `analytics-dev`. The other two are groundwork for analytics on
  those environments later; until then nothing but their own PostgreSQL is on them.

## Alternatives considered

- **Read production, as planned.** Production has no simulation to show, and the role would open
  real guests' bookings to the internet.
- **Externally shared dashboards instead of anonymous Viewer.** They run only the queries saved on
  the dashboard, so nobody can send SQL. They do not support variables, and every dashboard needs
  a location filter.
- **Names only for bots, through a view.** Keeps real people out of the statistics; rejected
  because seeing your own name there is part of the showcase.
- **The role's password from an application setting.** Needs a secret in the dev environment, a
  variable in the app compose file and in the deploy job, and still a migration to apply it.
- **Grafana on dev's private network.** No change to the app stack, but Grafana would sit next to
  the dev API, and a platform deploy would fail on a server where dev has not been deployed yet.
- **An analytics network for dev only.** One compose file serves every environment and cannot
  attach a network conditionally.

## Consequences

- Anyone can run any `SELECT` the role allows, including the names of everyone registered on dev
  next to their bookings and orders.
- PostgreSQL lets a role change its own password and reset its own defaults. One anonymous query
  can therefore lock Grafana out of the database or remove the timeout for good. A lock-out shows
  only as `unreachable` in the next platform deploy; a removed timeout is not reported. Recovery is a new migration that sets a fresh verifier and the defaults again, with
  the secret set again by `secrets.sh GRAFANA_DB_PASSWORD`, like a bot password rotation.
- With `statement_timeout` lifted, a visitor can keep the role's 5 connections busy: dashboards
  stall and dev PostgreSQL works harder. The connection limit and the container's memory limit
  bound the damage; production runs its own PostgreSQL.
- A query the role keeps running holds a read lock on its tables. A dev migration that alters one
  of them waits for that query, and API requests to the table queue behind the migration, so a
  visitor can stall a dev deploy. Migrations set no `lock_timeout` yet.
- The revokes close the two verified ways to fill the disk, not every way to write. The role can
  still write WAL with `pg_logical_emit_message`, which PostgreSQL recycles at checkpoints. The
  revokes hold in the application database only: in the cluster's `postgres` database the role
  may still create temporary tables and large objects, but Grafana's data source is bound to the
  application database. They also apply to any later
  non-owner role on dev.
- The role reads the system catalogs like any role: table and column names, row-count estimates
  and sizes of the tables it cannot read, and role names. Values of hidden columns stay hidden.
- A dashboard that needs another column or table needs a migration that grants it.
- Staging and production PostgreSQL are recreated once, at the promotion that adds their analytics
  network. Each then sits on a network that nothing else joins, which departs from the letter of
  AD-13 ("Every other Postgres and Redis stays on its project's private network").
- Like the bot migrations, `0021` depends on the environment it runs in. A dev dump restored into
  a fresh cluster has revision `0021` but no role, because roles are not part of a database dump.
  CI's migration round trip runs as `local`, so the dev branch is covered by the tests alone.

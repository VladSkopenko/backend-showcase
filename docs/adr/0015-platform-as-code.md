# 15. Platform as code

Date: 2026-11-11

## Status

Accepted. Tracked in [issue #26](https://github.com/VladSkopenko/backend-showcase/issues/26).
Amends [ADR 3](0003-deploy-entrypoint-verifies-commit.md): the platform deploys from `main`.

## Context

The platform stack ([ADR 7](0007-single-vm-platform-and-app-stacks.md)) will hold n8n, Prometheus,
Alertmanager, VictoriaLogs, Tempo and Grafana. Each of them needs the same things: a data directory
with the right owner, secrets, a memory limit, a healthcheck, configuration, and a web UI that only
the tailnet can reach. Several of these UIs refuse plain HTTP sign-in: n8n sets its session cookie
as `Secure`.

Done by hand, every service repeats the same steps on the server and in web consoles, and the
result drifts from the repository. Humans have no shell on the VM ([ADR 2](0002-ci-access-through-tailscale.md)),
so nothing can be fixed there by hand anyway. The platform also deploys only from `prod`, so a
change to monitoring has to be promoted through `rc` and `prod` like a product release.

## Decision

A merge to `main` deploys the whole platform. Every platform service is added through the
repository only.

- **The platform deploys from `main`.** The platform has no environments to promote between. The
  branch for the `platform` target lives in `deploy-entrypoint`, which cloud-init installs, so the
  change ships with one server replacement (`terraform apply -replace`, [ADR 8](0008-terraform-and-immutable-server.md))
  and a fresh one-off Tailscale auth key for the server.
- **One init service prepares the data.** A one-shot container in the platform compose creates every
  directory under `/srv/data/platform/<service>` with the owner that service runs as. The other
  services start after it completes. A new service adds one line to its list.
- **Secrets come from one place.** Every platform secret lives in the GitHub Environment `platform`.
  The deploy job sends them over stdin, as the app deploy does, and `deploy.sh` writes them to
  `/srv/platform/.env`. A script in the repository generates the values (encryption keys, passwords
  and their hashes) and stores them with `gh secret set`, so nobody types a secret into a console.
- **One HTTPS entry on the tailnet.** A `tailscale/tailscale` container joins the tailnet as its own
  node, `backend-showcase-platform`, tagged `tag:platform`, in userspace mode, so it needs no extra
  capabilities. It authenticates with an OAuth client secret, keeps its state under
  `/srv/data/platform/tailscale`, and serves each UI on its own HTTPS port of that node from a serve
  configuration in the repository. The certificate is a `*.ts.net` one, so browsers trust it and
  `Secure` cookies work. No public port opens ([ADR 2](0002-ci-access-through-tailscale.md)), and the
  server's base OS does not change.
- **Every service has the same shape.** A pinned image, a `mem_limit` that keeps all stacks within
  the VM's memory, a healthcheck so `up --wait` waits for it, data in
  `/srv/data/platform/<service>`, and configuration mounted read-only from `deploy/platform/<service>/`.
- **Services provision themselves.** Configuration that tools usually take through their UI comes
  from files and environment instead: Grafana provisioning, Prometheus and Alertmanager config, and
  for n8n the owner account (`N8N_INSTANCE_OWNER_*`), the workflow import, its credential built from a
  secret, and `n8n publish:workflow`. The repository is the source of truth; a change made in a UI is
  exported back into the repository or lost on the next deploy.

What stays manual, once:

- In the Tailscale admin console: enable MagicDNS and HTTPS certificates, add `tag:platform` to the
  tailnet policy, and create an OAuth client with the `auth_keys` scope for that tag. Managing the
  tailnet policy with Terraform (roadmap, Phase 5) removes most of this later.
- Run the secrets script once, and again only to rotate a secret.
- Replace the server once to switch the platform to `main`. Databases and platform data stay on the
  `prevent_destroy` block volume and media stay in Object Storage, but the replacement path has not
  been exercised yet (roadmap, Phase 5), so the databases are dumped by hand first.

## Alternatives considered

- **Set up each service by hand.** Fast for the first one, then six times the same steps, with no
  record in the repository and no way to rebuild the server without repeating them.
- **Tailscale Serve on the host.** Also gives `*.ts.net` HTTPS, but it is base OS configuration, so
  every change to the served ports means a server replacement.
- **Caddy with Tailscale certificates.** Needs the host's `tailscaled` socket inside the Caddy
  container and mixes the public and the private entry in one process.
- **Plain HTTP over the tailnet with `N8N_SECURE_COOKIE=false`.** The tailnet already encrypts the
  traffic, but each tool needs its own workaround, n8n advises against it, and browsers show the
  pages as insecure.
- **Keep deploying the platform from `prod`.** Keeps one release path for everything, but every
  monitoring change waits for two promotions and an approval meant for product releases.

## Consequences

- After the one-time steps, adding a platform service means a compose service, a line in the init
  list, a serve entry and, if needed, a secret in the script.
- Platform changes reach the server as soon as they merge. A broken platform change no longer waits
  for a promotion, so the deploy job must stay green on its own: `up --wait` fails the job when a
  healthcheck does.
- The node name `backend-showcase-platform.<tailnet>.ts.net` appears in public Certificate
  Transparency logs, as every HTTPS certificate does.
- Tailscale serve passes the visitor's identity headers (`Tailscale-User-Login`, checked live), but
  each UI keeps its own login; trusting those headers for sign-in is a separate decision.
- A new secret is added in three places: `deploy/platform/secrets.sh`, and the `deploy-platform`
  job's `env` and `printf` in `delivery.yml`.
- UI changes to n8n workflows and Grafana dashboards must be exported to the repository; a deploy
  overwrites the rest.

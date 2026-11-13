# Rollout

Status as of 2026-11-13. Who does each step is in brackets.

## Done

- [Vlad] Tailscale admin: HTTPS certificates enabled ([DNS](https://console.tailscale.com/admin/dns)),
  `tag:platform` in `tagOwners` plus a grant `autogroup:admin` → `tag:platform` on tcp 5678, 9090,
  9093, 9428 ([Access controls](https://console.tailscale.com/admin/acls)), OAuth client with Auth Keys
  write and `tag:platform` ([Trust credentials](https://console.tailscale.com/admin/settings/trust-credentials)).
- [Claude] Live check of the Tailscale container: proxy to another container by name over HTTPS
  works, `serve.json` format confirmed.

## PR A, `feature/platform-on-main`

Files, in order:

1. `deploy/terraform/deploy-entrypoint.sh`: target `platform` fetches and checks `main`.
2. `deploy/platform/deploy.sh`: header comment says `main`.
3. `.github/workflows/delivery.yml`: `deploy-platform` runs on `main`.

Rollout (the entrypoint reaches the server only through cloud-init, so the VM is replaced before the
merge; merging first would send a `main` commit to an entrypoint that still expects `prod`):

1. [Vlad] New one-off, pre-authorized server auth key with `tag:server` in
   [Keys](https://console.tailscale.com/admin/settings/keys), into `terraform.tfvars`.
2. [Vlad] Delete `backend-showcase-server` in [Machines](https://console.tailscale.com/admin/machines),
   so the new VM gets the same name and `DEPLOY_HOST` stays valid.
3. [Vlad] `terraform apply -replace=oci_core_instance.server` from the PR A branch.
4. [Vlad] Merge PR A. The push to `main` deploys dev and the platform (Caddy) on the new VM.

No database dump: `rc` and `prod` never deployed the app, dev data comes from migrations, the data
volume has `prevent_destroy` and cloud-init formats only an empty volume.

## PR B, `feature/platform-skeleton`

Files, in order, one at a time:

1. `deploy/platform/compose.yml`: init, tailscale, n8n, prometheus, alertmanager, victoria-logs,
   tempo, grafana, caddy healthcheck.
2. `deploy/platform/tailscale/serve.json`.
3. `deploy/platform/prometheus/prometheus.yml`, `deploy/platform/alertmanager/alertmanager.yml`,
   `deploy/platform/tempo/tempo.yaml`.
4. `deploy/platform/caddy/Caddyfile`: Grafana host.
5. `deploy/platform/secrets.sh`.
6. `.github/workflows/delivery.yml`: platform secrets in the job `env`, sent over stdin.
7. Docs: ADR 15 (Grafana public exception, Serve does pass identity headers, a new secret also edits
   `delivery.yml`), spine Stack table and Deferred Grafana item, `n8n/compose.yml` to 2.47.7.

[Claude] Before commit: each healthcheck command checked on throwaway containers of the pinned images.

Rollout:

1. [Vlad] Run `deploy/platform/secrets.sh` once.
2. [Vlad] Merge PR B; `deploy-platform` deploys the skeleton.
3. [Claude] Check the success signal in `SPEC.md`.

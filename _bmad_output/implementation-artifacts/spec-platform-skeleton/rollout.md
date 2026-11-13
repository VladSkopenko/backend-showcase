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

Files: init, tailscale and n8n in `deploy/platform/compose.yml`, `deploy/platform/tailscale/serve.json`
(n8n only), `deploy/platform/secrets.sh`, the `deploy-platform` job
sending the secrets, `deploy/platform/README.md`.

[Claude] Checked before commit: init script, the Tailscale service as a live test node, n8n with the
owner from env under its memory limit, the `.env` the job produces.

Rollout:

1. [Vlad] Review the diff, say "коммить".
2. [Vlad] Run `deploy/platform/secrets.sh` from the main checkout.
3. [Vlad] Merge PR B; `deploy-platform` deploys it.
4. [Claude] Watch the job and open n8n over the tailnet.

Later services follow `deploy/platform/README.md` ("Adding a service"), each in its own step of #26.
Docs still to update when Grafana lands: ADR 15 (Grafana public exception), spine Stack table and
Deferred Grafana item.

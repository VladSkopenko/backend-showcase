# 2. CI reaches the server only through Tailscale

Date: 2026-10-28

## Status

Accepted

## Context

GitHub Actions has to run deploys on the Oracle VM. The project runs for $0 in a public repository, and
its security baseline requires a closed SSH port. GitHub-hosted runners come from IP ranges far too wide
to allowlist. A self-hosted runner on the VM is not an option either: GitHub advises against them in
public repositories because a pull request from a fork can run code on the runner.

Tailscale is already in the stack to keep Prometheus, VictoriaLogs and n8n private.

## Decision

- The OCI security list opens only TCP 80 and 443. Port 22 is never public.
- Workflows join the tailnet with `tailscale/github-action@v4` through workload identity federation,
  as ephemeral nodes tagged `tag:ci`. GitHub stores no Tailscale secret.
- The tailnet policy allows `tag:ci` to reach `tag:server` on port 22 and nothing else.
- sshd on the VM listens only on `tailscale0`. A dedicated `deploy` user has one SSH key per target
  (`dev`, `staging`, `prod`, `platform`), each kept in the matching GitHub Environment and pinned to a
  forced command (see [ADR 3](0003-deploy-entrypoint-verifies-commit.md)).
- Secrets travel over SSH stdin and land in the target's `.env` with mode 600, never in argv or logs.
- The server joins the tailnet once at first boot with a one-off, pre-authorized, short-lived auth key,
  because that key ends up in cloud-init `user_data` and Terraform state.
- Break-glass access is the OCI serial console, tested once and written down in a runbook.

## Alternatives considered

- **Public SSH with an IP allowlist.** GitHub's ranges are too broad, so in practice port 22 would be
  open to the internet.
- **Self-hosted runner on the VM.** Unsafe in a public repository.
- **Tailscale SSH instead of OpenSSH.** No keys to manage, but nothing restricts what an authorized
  session can run. A forced command can, and that matters because the `docker` group is
  root-equivalent.
- **Pull-based deploys (an agent on the VM polls GHCR).** No inbound access at all, but the health gate
  and rollback would move out of the pipeline, where nobody sees them.

## Consequences

- The VM has no public management surface, and the whole access policy fits in one tailnet policy file.
- A leaked deploy key reaches only one target and can only start the deploy entrypoint.
- If Tailscale breaks on the VM, the only way in is the serial console, so the runbook has to be kept
  current.

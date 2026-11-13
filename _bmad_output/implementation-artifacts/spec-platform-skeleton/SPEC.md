---
id: SPEC-platform-skeleton
companions:
  - services.md
  - rollout.md
  - ../../../docs/adr/0015-platform-as-code.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Platform skeleton (issue #26, step 2)

## Why

Mandate from ADR 15: a merge to `main` deploys the whole platform with no manual steps on the
server. Today the platform deploys only from `prod` and holds only Caddy. This step switches the
platform to `main` and brings up every platform service empty, healthy and reachable, so each
later step of issue #26 only fills one service with content.

## Capabilities

- **CAP-1**
  - **intent:** A push to `main` deploys the platform stack.
  - **success:** After the merge, the `deploy-platform` job on `main` is green and the server's entrypoint accepted the `main` commit.
- **CAP-2**
  - **intent:** Every platform service gets its data directory with the right owner without any manual step on the server.
  - **success:** On an empty `/srv/data/platform`, one deploy starts every service and each writes its data.
- **CAP-3**
  - **intent:** Platform secrets come only from the GitHub Environment `platform`, generated and stored by one script.
  - **success:** One run of `deploy/platform/secrets.sh` stores every secret; a deploy writes them to `/srv/platform/.env` (mode 600); no secret appears in argv or job logs.
- **CAP-4**
  - **intent:** The private UIs (n8n, Prometheus, Alertmanager, VictoriaLogs) are reachable only over the tailnet, over trusted HTTPS, each on its own port of one node.
  - **success:** From an admin device each UI opens at `https://<PLATFORM_HOST>:<port>` with a valid `*.ts.net` certificate; none is reachable from the internet.
- **CAP-5**
  - **intent:** n8n runs empty and its owner can sign in.
  - **success:** The owner signs in over the tailnet with Vlad's existing email and password; no setup page is shown.
- **CAP-6**
  - **intent:** Anyone can look at Grafana without an account; only the admin can change it.
  - **success:** `https://backend-showcase-grafana.duckdns.org` opens without sign-in as Viewer; the admin signs in with the generated password.
- **CAP-7**
  - **intent:** Prometheus, Alertmanager, VictoriaLogs and Tempo run empty and healthy.
  - **success:** Each passes its healthcheck after the deploy.
- **CAP-8**
  - **intent:** Every platform service has the same shape.
  - **success:** Each service in `deploy/platform/compose.yml` has a pinned image, `mem_limit`, healthcheck, data under `/srv/data/platform/<service>` and read-only config from `deploy/platform/<service>/` where it has config; `up --wait` fails the job when any healthcheck fails.

## Constraints

- Two PRs: PR A `feature/platform-on-main` (CAP-1), then PR B `feature/platform-skeleton` (CAP-2 to CAP-8). Order and manual steps in `rollout.md`.
- Public surface stays 80/443 through Caddy (AD-3). Only Grafana is public; the other UIs only on the tailnet.
- The base OS changes only through the one VM replacement in PR A (ADR 8).
- State only in bind mounts under `/srv/data/platform/<service>`; no named volumes (AD-11).
- Each secret is its own GitHub secret, listed in the job `env` and sent over stdin; no `toJSON(secrets)`, no single blob of all secrets.
- The bcrypt hash is written to `.env` in single quotes; unquoted or double-quoted values lose the salt.
- The init service has `restart: "no"` and every other service depends on it with `condition: service_completed_successfully`, or `up --wait` fails on its exit.
- Config is mounted as a directory, never a single file: git replaces files on checkout, and the Tailscale container watches the serve file's directory.
- Tailscale runs in userspace mode with no extra capabilities, state on the data volume and `TS_AUTH_ONCE=true`, so the node keeps its name across restarts and VM replacement.
- Memory limits from `services.md`; all stacks together stay within the 12 GB VM with OS headroom (AD-12).
- App stacks get no dependency on the platform (AD-14).
- Every config key and enum value is checked against official docs while writing. Infra files are written one at a time, each key explained to Vlad.

## Non-goals

- n8n content: the simulator workflow, its credential, the dev API URL, publishing (step 3). n8n joins `edge` then.
- Prometheus targets and exporters, the `observability` and `analytics` networks.
- Log shipping, Grafana data sources and dashboards, traces, alert routing to Telegram.
- Sign-in for Prometheus, Alertmanager and VictoriaLogs; the tailnet policy is their boundary.
- A dump of the databases before the VM replacement (see `rollout.md`).

## Success signal

- After PR B merges, the `deploy-platform` job on `main` is green; Vlad opens n8n, Prometheus, Alertmanager and VictoriaLogs over the tailnet with HTTPS and signs in to n8n as the owner; a browser outside the tailnet opens Grafana as anonymous Viewer.

## Assumptions

- Caddy also gets a healthcheck, to match the ADR 15 shape.
- The platform node host name reaches compose as the GitHub Environment variable `PLATFORM_HOST`, sent over stdin like `MEDIA_PUBLIC_BASE_URL`.
- n8n keeps its default SQLite database under `/srv/data/platform/n8n`.
- The memory limits are starting points, to be tuned after measuring.

# Platform services

Versions, owners and health endpoints verified on 2026-11-13 against official releases, Dockerfiles
and image manifests (linux/arm64).

| Service | Image | Runs as (init owner) | Data mount | mem_limit | Healthcheck | Tailnet port |
|---|---|---|---|---|---|---|
| init | `busybox:1.38.0` | root | `/srv/data/platform` | 32m | none (one-shot, `restart: "no"`) | none |
| tailscale | `tailscale/tailscale:v1.104.7` | 0:0 | `/var/lib/tailscale` | 128m | `wget` `http://127.0.0.1:9002/healthz` (`TS_ENABLE_HEALTH_CHECK=true`) | serves the others |
| n8n | `n8nio/n8n:2.47.7` | 1000:1000 | `/home/node/.n8n` | 768m | `wget` `http://127.0.0.1:5678/healthz/readiness` | 5678 |
| prometheus | `prom/prometheus:v3.15.1` | 65534:65534 | `/prometheus` | 512m | `wget` `http://127.0.0.1:9090/-/ready` | 9090 |
| alertmanager | `prom/alertmanager:v0.35.0` | 65534:65534 | `/alertmanager` | 64m | `wget` `http://127.0.0.1:9093/-/ready` | 9093 |
| victoria-logs | `victoriametrics/victoria-logs:v1.54.0` | 0:0 | `/victoria-logs-data` | 256m | `/victoria-logs-prod -healthcheck` (distroless, no wget) | 9428 |
| tempo | `grafana/tempo:3.1.1` (no `v`) | 10001:10001 | `/var/tempo` | 512m | `/tempo --health` (distroless) | none, no UI |
| grafana | `grafana/grafana:13.2.6` | 472:0 | `/var/lib/grafana` | 256m | `wget` `http://127.0.0.1:3000/api/health` | none, public via Caddy |
| caddy | `caddy:2.11` (unchanged) | 0:0 | `/data`, `/config` | 128m (unchanged) | added, endpoint picked from Caddy docs | none, public 80/443 |

Platform total about 2.6 GB. App stacks today 3 × (512m + 256m) = 2.3 GB, plus about 1.5 GB reserved
for future Redis, exporters and workers: about 6.5 GB of 12 GB.

## Per-service settings

- **tailscale:** `TS_AUTHKEY` = OAuth client secret + `?ephemeral=false&preauthorized=true`;
  `TS_EXTRA_ARGS=--advertise-tags=tag:platform`; `TS_HOSTNAME=backend-showcase-platform`;
  `TS_STATE_DIR=/var/lib/tailscale`; `TS_AUTH_ONCE=true`; `TS_SERVE_CONFIG` pointing into the mounted
  `deploy/platform/tailscale/` directory. Userspace is the default; no `cap_add`, no `/dev/net/tun`.
- **serve.json:** per port `"TCP": {"<port>": {"HTTPS": true}}` and
  `"Web": {"${TS_CERT_DOMAIN}:<port>": {"Handlers": {"/": {"Proxy": "http://<service>:<port>"}}}}`.
  Malformed JSON stops the container.
- **n8n:** `N8N_ENCRYPTION_KEY`; owner through `N8N_INSTANCE_OWNER_MANAGED_BY_ENV=true`,
  `N8N_INSTANCE_OWNER_EMAIL`, `N8N_INSTANCE_OWNER_PASSWORD_HASH` (bcrypt), first and last name;
  `N8N_HOST`, `N8N_PROTOCOL=https`, `N8N_EDITOR_BASE_URL=https://<PLATFORM_HOST>:5678`,
  `N8N_PROXY_HOPS=1`; `GENERIC_TIMEZONE` and `TZ` `Asia/Tbilisi` as locally.
- **grafana:** `GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer`,
  `GF_SECURITY_ADMIN_PASSWORD` (applies only on first start), `GF_SERVER_ROOT_URL` =
  `https://backend-showcase-grafana.duckdns.org`; joins `edge`; Caddy routes that host to `grafana:3000`.
- **prometheus:** own `prometheus.yml` that scrapes itself.
- **alertmanager:** own `alertmanager.yml` with one route to a receiver that sends nothing.
- **tempo:** own `tempo.yaml`: monolithic, `storage.trace.backend: local` under `/var/tempo`, OTLP
  receivers, usage report off.
- **victoria-logs:** `-storageDataPath=/victoria-logs-data`, no config file.

## Secrets and variables (GitHub Environment `platform`)

| Name | Kind | Source |
|---|---|---|
| `TS_AUTHKEY` | secret | OAuth client secret entered by Vlad; the script appends the query parameters |
| `N8N_ENCRYPTION_KEY` | secret | generated, `openssl rand -hex 32`; never rotated (credentials depend on it) |
| `N8N_OWNER_EMAIL` | secret | entered by Vlad (kept out of public logs) |
| `N8N_OWNER_PASSWORD_HASH` | secret | bcrypt of the password Vlad enters; tool chosen when writing the script, `$2a`/`$2b` prefix |
| `GRAFANA_ADMIN_PASSWORD` | secret | generated, printed once |
| `PLATFORM_HOST` | variable | `backend-showcase-platform.<tailnet>.ts.net` |

Existing `DEPLOY_SSH_KEY` stays as is and never goes into `.env`.

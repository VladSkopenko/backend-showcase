# Platform stack

One compose project with the platform services, deployed by the `deploy-platform` job on every push
to `main` ([ADR 15](../../docs/adr/0015-platform-as-code.md)).

## Secrets

All platform secrets live in the GitHub Environment `platform`. `secrets.sh` creates them; nobody
types a secret into the GitHub UI.

```bash
deploy/platform/secrets.sh               # sets only the secrets that are missing
deploy/platform/secrets.sh TS_AUTHKEY    # (re)sets exactly the named ones, to rotate
```

It asks for what only a person knows (the Tailscale OAuth client secret, the n8n owner's email and
password) and generates the rest. Values go to `gh secret set` over stdin, never into argv or output.
Running it again without arguments is safe: existing secrets, including `N8N_ENCRYPTION_KEY`, stay.

| Name | Kind | Value |
|---|---|---|
| `TS_AUTHKEY` | secret | Tailscale OAuth client secret plus `?ephemeral=false&preauthorized=true`. Reusable; the container uses it only when it has no state yet. |
| `N8N_ENCRYPTION_KEY` | secret | Generated. Never rotate it: n8n's saved credentials become unreadable. |
| `N8N_OWNER_EMAIL` | secret | Entered. |
| `N8N_OWNER_PASSWORD_HASH` | secret | bcrypt of the entered password. |
| `PLATFORM_HOST` | variable | `backend-showcase-platform.<tailnet>.ts.net`, derived from `DEPLOY_HOST`. |

## Adding a service

1. A service in `compose.yml`: pinned image, `mem_limit`, healthcheck, `depends_on` init, data under
   `/srv/data/platform/<service>`, config from `deploy/platform/<service>/` mounted read-only as a
   directory.
2. One line in the init service: the data directory with the uid:gid the image runs as.
3. If it has a private UI: a port in `tailscale/serve.json` and the same port in the tailnet policy grant.
4. If it needs a secret: a block in `secrets.sh`, the name in the `deploy-platform` job's `env` and
   `printf` in `.github/workflows/delivery.yml`, then run `secrets.sh` without arguments before the merge.

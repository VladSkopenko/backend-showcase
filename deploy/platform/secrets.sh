#!/usr/bin/env bash
# Stores the platform secrets in the GitHub Environment "platform" (ADR 15). Run it locally from the
# repository: with no arguments it sets only the secrets that are missing; with names it (re)sets
# exactly those, e.g. `deploy/platform/secrets.sh TS_AUTHKEY` to rotate one.
# Needs: gh (signed in with access to the repo), openssl, docker (for the bcrypt hash and the SCRAM verifier).
set -euo pipefail
cd "$(dirname "$0")"

env=platform

# Names only; values are never printed or passed in argv. gh reads each value from stdin.
existing=$(gh secret list --env "$env" --json name --jq '.[].name')

wanted() {
  if [[ -n "$requested" ]]; then
    [[ " $requested " == *" $1 "* ]]
  elif grep -qx "$1" <<< "$existing"; then
    return 1
  fi
}

store() {
  printf '%s' "$2" | gh secret set "$1" --env "$env"
}

requested="${*:-}"

# Tailscale: the OAuth client secret from the admin console (Trust credentials). The query parameters
# make the platform node permanent and skip device approval.
if wanted TS_AUTHKEY; then
  read -rsp 'Tailscale OAuth client secret (tskey-client-...): ' ts_secret; echo
  store TS_AUTHKEY "$ts_secret?ephemeral=false&preauthorized=true"
fi

# n8n encrypts saved credentials with this key. Rotating it makes them unreadable.
if wanted N8N_ENCRYPTION_KEY; then
  store N8N_ENCRYPTION_KEY "$(openssl rand -hex 32)"
fi

if wanted N8N_OWNER_EMAIL; then
  read -rp 'n8n owner email: ' owner_email
  store N8N_OWNER_EMAIL "$owner_email"
fi

# Only the bcrypt hash leaves this machine; caddy reads the password from stdin.
if wanted N8N_OWNER_PASSWORD_HASH; then
  read -rsp 'n8n owner password: ' owner_password; echo
  hash=$(printf '%s' "$owner_password" | docker run -i --rm caddy:2.11 caddy hash-password)
  store N8N_OWNER_PASSWORD_HASH "$hash"
fi

# Grafana's read-only database role on dev (ADR 19). The password goes only to GitHub; its
# SCRAM verifier is public and goes into the migration that creates the role. postgres:18
# computes it in single-user mode with the password on stdin. stderr is dropped: a failing
# statement would be logged together with the password.
if wanted GRAFANA_DB_PASSWORD; then
  db_password=$(openssl rand -hex 32)
  verifier=$(printf "CREATE ROLE r PASSWORD '%s';\nSELECT rolpassword FROM pg_authid WHERE rolname = 'r';\n" "$db_password" \
    | docker run -i --rm --user postgres postgres:18 \
        sh -c 'initdb -D /tmp/data > /dev/null 2>&1 && postgres --single -D /tmp/data postgres 2> /dev/null' \
    | grep -o 'SCRAM-SHA-256\$[^"]*') || { echo 'could not compute the SCRAM verifier' >&2; exit 1; }
  store GRAFANA_DB_PASSWORD "$db_password"
  echo "grafana_reader verifier for the migration (public): $verifier"
fi

# Not a secret: the platform node's tailnet name, derived from the server's name in DEPLOY_HOST.
deploy_host=$(gh variable get DEPLOY_HOST)
gh variable set PLATFORM_HOST --env "$env" --body "backend-showcase-platform.${deploy_host#*.}"

echo "platform secrets stored"

#!/usr/bin/env bash
# Stores the platform secrets in the GitHub Environment "platform" (ADR 15). Run it locally from the
# repository: with no arguments it sets only the secrets that are missing; with names it (re)sets
# exactly those, e.g. `deploy/platform/secrets.sh TS_AUTHKEY` to rotate one.
# Needs: gh (signed in with access to the repo), openssl, docker (for the bcrypt hash).
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

# Not a secret: the platform node's tailnet name, derived from the server's name in DEPLOY_HOST.
deploy_host=$(gh variable get DEPLOY_HOST)
gh variable set PLATFORM_HOST --env "$env" --body "backend-showcase-platform.${deploy_host#*.}"

echo "platform secrets stored"

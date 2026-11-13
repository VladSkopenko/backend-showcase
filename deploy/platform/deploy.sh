#!/usr/bin/env bash
# Started by the deploy entrypoint from a verified commit on main, inside the repo checkout (ADR 3, ADR 15).
# Secrets arrive on stdin and land in /srv/platform/.env.
set -euo pipefail

dir=/srv/platform

umask 077
cat > "$dir/.env.new"
mv "$dir/.env.new" "$dir/.env"

docker network inspect edge > /dev/null 2>&1 || docker network create edge > /dev/null
compose=(docker compose --project-name platform --file deploy/platform/compose.yml --env-file "$dir/.env")
"${compose[@]}" up --detach --wait --wait-timeout 120
# compose does not notice a changed Caddyfile, so Caddy reloads it explicitly.
"${compose[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile

echo "platform deployed"

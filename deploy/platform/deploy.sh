#!/usr/bin/env bash
# Started by the deploy entrypoint from a verified commit on main, inside the repo checkout (ADR 3, ADR 15).
# Secrets arrive on stdin and land in /srv/platform/.env.
set -euo pipefail

dir=/srv/platform

umask 077
cat > "$dir/.env.new"
mv "$dir/.env.new" "$dir/.env"

docker network inspect edge > /dev/null 2>&1 || docker network create edge > /dev/null
# Grafana's way to the dev database (ADR 19). Internal, and also created by the dev deploy:
# whichever deploy runs first makes it.
docker network inspect analytics-dev > /dev/null 2>&1 || docker network create --internal analytics-dev > /dev/null
compose=(docker compose --project-name platform --file deploy/platform/compose.yml --env-file "$dir/.env")
"${compose[@]}" up --detach --wait --wait-timeout 120
# compose does not notice a changed Caddyfile, so Caddy reloads it explicitly.
"${compose[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile

# Grafana's own healthcheck passes without the dev database, so its data source is probed here.
# Reported, not enforced: the platform must deploy even when dev is down (ADR 19).
if "${compose[@]}" exec -T grafana wget -q -O /dev/null http://127.0.0.1:3000/api/datasources/uid/restaurant-dev/health; then
  datasource=ok
else
  datasource=unreachable
fi

echo "platform deployed, grafana data source: $datasource"

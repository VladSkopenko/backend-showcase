#!/usr/bin/env bash
set -euo pipefail

dir=/srv/platform

umask 077
cat > "$dir/.env.new"
mv "$dir/.env.new" "$dir/.env"

docker network inspect edge > /dev/null 2>&1 || docker network create edge > /dev/null
docker network inspect analytics-dev > /dev/null 2>&1 || docker network create --internal analytics-dev > /dev/null
docker network inspect observability > /dev/null 2>&1 || docker network create --internal observability > /dev/null
compose=(docker compose --project-name platform --file deploy/platform/compose.yml --env-file "$dir/.env")
"${compose[@]}" run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml > /dev/null
"${compose[@]}" up --detach --wait --wait-timeout 120
"${compose[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
"${compose[@]}" exec -T prometheus kill -s HUP 1
"${compose[@]}" restart fluent-bit

if "${compose[@]}" exec -T grafana wget -q -O /dev/null http://127.0.0.1:3000/api/datasources/uid/restaurant-dev/health; then
  datasource=ok
else
  datasource=unreachable
fi

echo "platform deployed, prometheus reloaded, grafana data source: $datasource"

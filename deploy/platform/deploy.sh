#!/usr/bin/env bash
# Started by the deploy entrypoint from a verified commit on main, inside the repo checkout.
# Secrets arrive on stdin and land in /srv/platform/.env.
set -euo pipefail

dir=/srv/platform

umask 077
cat > "$dir/.env.new"
mv "$dir/.env.new" "$dir/.env"

docker network inspect edge > /dev/null 2>&1 || docker network create edge > /dev/null
# Grafana's way to the dev database. Internal, and also created by the dev deploy:
# whichever deploy runs first makes it.
docker network inspect analytics-dev > /dev/null 2>&1 || docker network create --internal analytics-dev > /dev/null
# Prometheus's way to each environment's API. Internal, and also created by the app
# deploys: whichever deploy runs first makes it.
docker network inspect observability > /dev/null 2>&1 || docker network create --internal observability > /dev/null
compose=(docker compose --project-name platform --file deploy/platform/compose.yml --env-file "$dir/.env")
# Checked before anything changes: on SIGHUP a bad config is only logged, and a recreated
# container would exit on it. Errors go to stderr; stdout would land in the job summary.
"${compose[@]}" run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml > /dev/null
"${compose[@]}" up --detach --wait --wait-timeout 120
# compose does not notice a changed Caddyfile, so Caddy reloads it explicitly.
"${compose[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
# Nor a changed prometheus.yml; Prometheus rereads it on SIGHUP (lifecycle API stays off).
# Sent from inside: docker kill marks the container manually stopped for any signal, and
# restart: unless-stopped would then no longer bring Prometheus back. PID 1 is Prometheus.
"${compose[@]}" exec -T prometheus kill -s HUP 1

# Grafana's own healthcheck passes without the dev database, so its data source is probed here.
# Reported, not enforced: the platform must deploy even when dev is down.
if "${compose[@]}" exec -T grafana wget -q -O /dev/null http://127.0.0.1:3000/api/datasources/uid/restaurant-dev/health; then
  datasource=ok
else
  datasource=unreachable
fi

echo "platform deployed, prometheus reloaded, grafana data source: $datasource"

#!/usr/bin/env bash
# Started by the deploy entrypoint from a verified commit, inside the repo checkout.
# Secrets arrive on stdin and land in the environment's .env; the image is resolved to a digest.
set -euo pipefail

env="${1:?usage: deploy.sh <dev|staging|prod>}"
image=ghcr.io/vladskopenko/backend-showcase/backend
dir="/srv/app/$env"
project="app-$env"

tag="tree-$(git rev-parse 'HEAD^{tree}')"
docker pull --quiet "$image:$tag" > /dev/null
digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$image:$tag")

umask 077
{
  cat
  echo "APP_ENV=$env"
  echo "IMAGE=$digest"
} > "$dir/.env.new"
mv "$dir/.env.new" "$dir/.env"

docker network inspect edge > /dev/null 2>&1 || docker network create edge > /dev/null
# Internal: the network itself gives no route outside the host. The platform deploy creates
# analytics-dev the same way, so whichever deploy runs first makes it.
docker network inspect "analytics-$env" > /dev/null 2>&1 || docker network create --internal "analytics-$env" > /dev/null
# Every environment's API joins it, so Prometheus can scrape it. Internal, and also
# created by the platform deploy: whichever deploy runs first makes it.
docker network inspect observability > /dev/null 2>&1 || docker network create --internal observability > /dev/null
compose=(docker compose --project-name "$project" --file deploy/app/compose.yml --env-file "$dir/.env")
# Postgres first; an unchanged postgres service is left running on redeploys.
"${compose[@]}" up --detach --wait --wait-timeout 120 postgres
# Migrate with the new image before it serves traffic. A failed migration rolls back in its own
# transaction and stops the deploy here, leaving the running API untouched.
"${compose[@]}" run --rm --no-deps api alembic upgrade head
"${compose[@]}" up --detach --wait --wait-timeout 120 api
# The exporter's role exists only on dev (migration 0026). Started after the API, so a missing
# secret or a wrong password fails the deploy here and leaves the running API untouched.
if [[ "$env" == dev ]]; then
  "${compose[@]}" up --detach --wait --wait-timeout 120 postgres-exporter
fi

echo "deployed $digest"

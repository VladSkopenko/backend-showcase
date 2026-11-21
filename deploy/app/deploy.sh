#!/usr/bin/env bash
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
docker network inspect "analytics-$env" > /dev/null 2>&1 || docker network create --internal "analytics-$env" > /dev/null
docker network inspect observability > /dev/null 2>&1 || docker network create --internal observability > /dev/null
compose=(docker compose --project-name "$project" --file deploy/app/compose.yml --env-file "$dir/.env")
"${compose[@]}" up --detach --wait --wait-timeout 120 postgres
"${compose[@]}" run --rm --no-deps api alembic upgrade head
"${compose[@]}" up --detach --wait --wait-timeout 120 api
if [[ "$env" == dev ]]; then
  "${compose[@]}" up --detach --wait --wait-timeout 120 postgres-exporter
fi

echo "deployed $digest"

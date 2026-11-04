#!/usr/bin/env bash
# Started by the deploy entrypoint from a verified commit, inside the repo checkout (ADR 3).
# Secrets arrive on stdin and land in the environment's .env; the image is resolved to a digest (AD-7).
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
docker compose --project-name "$project" --file deploy/app/compose.yml --env-file "$dir/.env" up --detach --wait --wait-timeout 120

echo "deployed $digest"

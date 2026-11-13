#!/usr/bin/env bash
# Forced command of the deploy user (ADR 3). The target comes from authorized_keys, the commit sha from
# the SSH client. Secrets stay on stdin and pass through to deploy.sh, which writes the .env.
set -euo pipefail

target="${1:?usage: deploy-entrypoint <dev|staging|prod|platform>}"
sha="${SSH_ORIGINAL_COMMAND:-}"

case "$target" in
  dev) branch=main stack=app ;;
  staging) branch=rc stack=app ;;
  prod) branch=prod stack=app ;;
  # The platform has one instance for every environment, so it deploys straight from main (ADR 15).
  platform) branch=main stack=platform ;;
  *) echo "unknown target: $target" >&2; exit 1 ;;
esac

if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "expected a full 40-character commit sha" >&2
  exit 1
fi

# One clone per target, so concurrent deploys of different targets never share a working tree.
repo="/srv/deploy/$target"
if [[ ! -d "$repo/.git" ]]; then
  git clone --quiet --no-checkout https://github.com/VladSkopenko/backend-showcase.git "$repo"
fi

git -C "$repo" fetch --quiet origin "$branch"
if ! git -C "$repo" merge-base --is-ancestor "$sha" "origin/$branch"; then
  echo "commit $sha is not on $branch" >&2
  exit 1
fi

git -C "$repo" checkout --quiet --force --detach "$sha"
cd "$repo"
exec "deploy/$stack/deploy.sh" "$target"

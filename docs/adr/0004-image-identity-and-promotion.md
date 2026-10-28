# 4. Images are identified by tree hash and promoted by digest

Date: 2026-10-28

## Status

Accepted

## Context

`main` deploys to dev, `rc` to staging and `prod` to production. The same image has to move up the
chain without being rebuilt. Promotion happens through pull requests, and GitHub merges them with a
merge commit, which gets a new sha. An image tagged with the `main` commit sha is therefore not found
from `rc`. Using the merge commit's second parent (`HEAD^2`) finds it, but it silently deploys the wrong
code when `rc` holds changes that `main` does not.

Hotfixes have to go straight to `rc` from `hotfix/*` branches and then be cherry-picked into `main`.

## Decision

- An image is identified by the git tree hash, `git rev-parse HEAD^{tree}`. Two commits with the same
  tree contain byte-identical code. Images are also tagged `sha-<commit>` and carry the label
  `org.opencontainers.image.revision`, so humans can look them up.
- Each tree is built at most once. Any environment's pipeline looks up the tree tag first. If the image
  exists, it is reused; if not, it is built for `linux/arm64`, scanned with Trivy and pushed to GHCR.
  A promotion that finds no image fails with an explicit message and does not wait.
- Deploys use the digest, `image@sha256:...`, resolved once. The VM keeps the previous digest, and
  rollback starts that digest.
- `rc` accepts pull requests from `main` or `hotfix/*`, and `prod` only from `rc`. A required status
  check enforces this. Rulesets allow merge commits only on `rc` and `prod`.
- A required check on every `main` to `rc` pull request compares the merge result's tree with `main`'s
  tree. If they differ, a hotfix was not carried back to `main`, and the check lists the files involved.

## Alternatives considered

- **Merge commit's second parent.** Silently wrong once the branches diverge.
- **A manifest file or the Deployments API as the source of truth.** Works, but adds state to keep in
  sync.
- **Tag-based promotion without environment branches.** Simpler, but the README settles on branches
  with pull requests and an approval for production.

## Consequences

- The README rule "built once per commit on `main`" becomes "each tree is built at most once". Regular
  promotions never rebuild; a hotfix builds once when it reaches `rc`, and production runs that same
  image.
- A forgotten cherry-pick blocks the next promotion instead of shipping untested code to staging.
- Mutable registry tags cannot change what runs.

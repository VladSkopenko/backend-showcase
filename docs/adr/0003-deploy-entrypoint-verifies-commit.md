# 3. The deploy entrypoint takes a commit and verifies it

Date: 2026-10-28

## Status

Accepted

## Context

Deploy keys are pinned to a forced command ([ADR 2](0002-ci-access-through-tailscale.md)). A forced
command blocks `scp` and `rsync`, so compose files and deploy logic need another way onto the VM. If the
caller streamed them in, a leaked key could start any compose file it liked. With access to the Docker
socket, that is root.

## Decision

- cloud-init installs a small entrypoint. Its only argument is a commit sha.
- The entrypoint keeps a clone of the public repository and fetches the branch of its target (`main` for
  dev, `rc` for staging, `prod` for production and platform).
- It refuses any commit that is not reachable from that branch (`git merge-base --is-ancestor`).
- It then runs `deploy/app/deploy.sh` or `deploy/platform/deploy.sh` from that commit, so the deploy
  logic is versioned and reviewed together with the code.
- The app `deploy.sh` resolves the image itself: the commit's tree hash gives the tag, the tag gives the
  digest ([ADR 4](0004-image-identity-and-promotion.md)). It prints the digest for the job summary.

## Alternatives considered

- **Caller streams a tarball of `deploy/` on stdin.** Simple, but a leaked key could deploy arbitrary
  compose files.
- **Caller passes a digest.** A leaked key could start any image from the registry, including an old,
  vulnerable one.
- **Baking deploy logic into cloud-init.** Every change to `deploy.sh` would mean replacing the VM.

## Consequences

- Everything the VM runs comes from a protected branch. A leaked key can only redeploy a commit that has
  already passed review.
- The VM needs outbound HTTPS to GitHub, which it already has for pulling from GHCR.
- The entrypoint is the only deploy code that changes through cloud-init. It stays small for that reason.

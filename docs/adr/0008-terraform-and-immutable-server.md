# 8. Terraform from Phase 3, and the server is immutable

Date: 2026-10-28

## Status

Accepted

## Context

The README originally scheduled Terraform for Phase 5, but deploys in Phase 3 already need the VM.
Creating it by hand first and importing it later is busywork, and it weakens the infrastructure-as-code
story. Phase 5's goal, recreating the server with one command, also needs a way to bootstrap the
operating system.

## Decision

- Minimal Terraform comes first in Phase 3: VCN, subnet, a security list with 80 and 443, the VM, and a
  separate data block volume with `prevent_destroy`.
- State uses Terraform's native `oci` backend (Terraform 1.12 or later), in an Object Storage bucket with
  versioning. The bucket is created once by hand, and it is the only resource outside Terraform.
- cloud-init owns the base OS and runs once at first boot. It installs Docker and Tailscale, creates the
  `deploy` user with its forced-command entrypoint, binds sshd to `tailscale0`, mounts the data volume at
  `/srv/data`, and points the DuckDNS records at the VM's public IP.
- Layer ownership: Terraform owns the machine, cloud-init the OS, pipelines the stacks. Nothing on the
  VM is changed by hand.
- A base OS change means replacing the VM, `terraform apply -replace` on the instance. The data volume
  is reattached.

## Alternatives considered

- **Create the VM by hand, `terraform import` it in Phase 5.** Busywork that adds nothing.
- **Ansible for configuration.** A whole extra tool to keep a single VM in shape. With immutable
  replacement, cloud-init is enough.
- **S3-compatible backend on Object Storage.** Oracle deprecates it in favour of the native backend.

## Consequences

- Phase 5's "destroy and recreate with one command" falls out of Phase 3's setup.
- Changing the base OS is slower, because it is a replacement. That is the trade-off for no drift.
- The server's Tailscale auth key and the DuckDNS token end up in `user_data` and state. The auth key is
  one-off and short-lived.

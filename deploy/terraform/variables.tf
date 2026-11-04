variable "compartment_ocid" {
  description = "OCID of the backend-showcase compartment that holds every resource of the project"
  type        = string
}

variable "deploy_public_keys" {
  description = "Public SSH key of each deploy target (dev, staging, prod, platform), keyed by target"
  type        = map(string)
}

variable "duckdns_token" {
  description = "DuckDNS account token, used once at first boot to point the public hosts at the VM"
  type        = string
  sensitive   = true
}

variable "tailscale_auth_key" {
  description = "One-off, pre-authorized Tailscale auth key tagged tag:server, used once at first boot"
  type        = string
  sensitive   = true
}

variable "ubuntu_password_hash" {
  description = "SHA-512 crypt hash of the ubuntu password, for serial console break-glass access"
  type        = string
  sensitive   = true
}

variable "compartment_ocid" {
  description = "OCID of the backend-showcase compartment that holds every resource of the project"
  type        = string
}

variable "media_writer_email" {
  description = "Email for the media writer users; identity domains require one. Use a plus-address, e.g. you+media-{env}@gmail.com, where {env} is replaced per environment"
  type        = string

  validation {
    # Without the placeholder every environment's writer user would get the same email.
    condition     = strcontains(var.media_writer_email, "{env}")
    error_message = "media_writer_email must contain {env}, e.g. you+media-{env}@gmail.com."
  }
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

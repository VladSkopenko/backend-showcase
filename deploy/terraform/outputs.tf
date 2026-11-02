output "server_public_ip" {
  description = "Public IP of the VM, the target of the DuckDNS records"
  value       = oci_core_instance.server.public_ip
}

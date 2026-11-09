output "server_public_ip" {
  description = "Public IP of the VM, the target of the DuckDNS records"
  value       = oci_core_instance.server.public_ip
}

output "media_s3_endpoint" {
  description = "S3 Compatibility API endpoint for the media buckets"
  value       = "https://${data.oci_objectstorage_namespace.this.namespace}.compat.objectstorage.${local.region}.oci.customer-oci.com"
}

output "media_public_base_urls" {
  description = "Public base URL of each media bucket; an object's URL is this plus its key (format to confirm with a first upload)"
  value = {
    for env, bucket in oci_objectstorage_bucket.media :
    env => "https://objectstorage.${local.region}.oraclecloud.com/n/${bucket.namespace}/b/${bucket.name}/o"
  }
}

output "media_access_key_ids" {
  description = "Access key id of each media writer, for MEDIA_ACCESS_KEY_ID"
  value       = { for env, key in oci_identity_customer_secret_key.media_writer : env => key.id }
}

output "media_secret_keys" {
  description = "Secret key of each media writer, for MEDIA_SECRET_ACCESS_KEY; read with terraform output -json"
  value       = { for env, key in oci_identity_customer_secret_key.media_writer : env => key.key }
  sensitive   = true
}

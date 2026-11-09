# Dish pictures and other media live in Object Storage, one bucket per environment, so they
# survive the VM and stay isolated between environments. The API writes through the S3
# Compatibility API with a Customer Secret Key of a dedicated user that may touch only its bucket.
# Add "staging" and "prod" to media_environments when those environments go live.

locals {
  media_environments = toset(["dev"])
  region             = "eu-frankfurt-1"
  # Users and groups live in the tenancy; the project compartment sits directly under it.
  tenancy_ocid = data.oci_identity_compartment.project.compartment_id
}

data "oci_identity_compartment" "project" {
  id = var.compartment_ocid
}

data "oci_objectstorage_namespace" "this" {
  compartment_id = var.compartment_ocid
}

resource "oci_objectstorage_bucket" "media" {
  for_each = local.media_environments

  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.this.namespace
  name           = "backend-showcase-media-${each.key}"
  # Anyone may download an object by its URL; nobody may list the bucket anonymously.
  access_type = "ObjectReadWithoutList"
}

# Users and groups can only exist in the tenancy (root compartment); the policy stays in the
# project compartment, so it can grant nothing outside it.
resource "oci_identity_group" "media_writers" {
  for_each = local.media_environments

  compartment_id = local.tenancy_ocid
  name           = "backend-showcase-media-${each.key}-writers"
  description    = "Writes objects to the backend-showcase-media-${each.key} bucket"
}

resource "oci_identity_user" "media_writer" {
  for_each = local.media_environments

  compartment_id = local.tenancy_ocid
  name           = "backend-showcase-media-${each.key}-writer"
  description    = "API key holder for the ${each.key} media bucket; no console access"
  email          = replace(var.media_writer_email, "{env}", each.key)
}

resource "oci_identity_user_group_membership" "media_writer" {
  for_each = local.media_environments

  group_id = oci_identity_group.media_writers[each.key].id
  user_id  = oci_identity_user.media_writer[each.key].id
}

resource "oci_identity_policy" "media_writers" {
  for_each = local.media_environments

  compartment_id = var.compartment_ocid
  name           = "backend-showcase-media-${each.key}-writers"
  description    = "Lets the ${each.key} media writers manage objects in their bucket only"
  # manage objects covers create, overwrite and delete; S3 clients also read the bucket itself.
  statements = [
    "Allow group ${oci_identity_group.media_writers[each.key].name} to manage objects in compartment id ${var.compartment_ocid} where target.bucket.name = '${oci_objectstorage_bucket.media[each.key].name}'",
    "Allow group ${oci_identity_group.media_writers[each.key].name} to read buckets in compartment id ${var.compartment_ocid} where target.bucket.name = '${oci_objectstorage_bucket.media[each.key].name}'",
  ]
}

# The secret lands in the Terraform state, which lives in the private backend-showcase-tfstate
# bucket. Copy it into the GitHub Environment once, then read it back only from there.
resource "oci_identity_customer_secret_key" "media_writer" {
  for_each = local.media_environments

  user_id      = oci_identity_user.media_writer[each.key].id
  display_name = "backend-showcase-media-${each.key}-s3"
}

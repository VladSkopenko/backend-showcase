data "oci_core_images" "ubuntu" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "26.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_instance" "server" {
  compartment_id       = var.compartment_ocid
  availability_domain  = oci_core_volume.data.availability_domain
  shape                = "VM.Standard.A1.Flex"
  display_name         = "backend-showcase-server"
  preserve_boot_volume = false

  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu.images[0].id
    boot_volume_size_in_gbs = 50
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
  }

  metadata = {
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      deploy_entrypoint    = base64encode(file("${path.module}/deploy-entrypoint.sh"))
      deploy_public_keys   = var.deploy_public_keys
      duckdns_token        = var.duckdns_token
      tailscale_auth_key   = var.tailscale_auth_key
      ubuntu_password_hash = var.ubuntu_password_hash
    }))
  }

  lifecycle {
    ignore_changes = [source_details[0].source_id]
  }
}

data "oci_identity_availability_domains" "this" {
  compartment_id = var.compartment_ocid
}

resource "oci_core_volume" "data" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.this.availability_domains[0].name
  display_name        = "backend-showcase-data"
  size_in_gbs         = 50

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_volume_attachment" "data" {
  attachment_type = "paravirtualized"
  instance_id     = oci_core_instance.server.id
  volume_id       = oci_core_volume.data.id
  device          = "/dev/oracleoci/oraclevdb"
  display_name    = "backend-showcase-data"
}

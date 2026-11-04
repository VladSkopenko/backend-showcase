terraform {
  required_version = ">= 1.12"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 9.11"
    }
  }

  backend "oci" {
    bucket              = "backend-showcase-tfstate"
    namespace           = "fr76arfm8eim"
    key                 = "backend-showcase/terraform.tfstate"
    region              = "eu-frankfurt-1"
    auth                = "APIKey"
    config_file_profile = "backend-showcase"
  }
}

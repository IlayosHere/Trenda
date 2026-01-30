# ============================================================================
# Terraform Backend Configuration
# Uses Google Cloud Storage for remote state management
# ============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Backend configuration - bucket must be created before first terraform init
  # Use the deploy script to create this bucket automatically
  backend "gcs" {
    bucket = "trenda-terraform-state"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

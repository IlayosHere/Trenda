# ============================================================================
# IAM Configuration
# Minimal permission Service Account for the VM
# ============================================================================

# -----------------------------------------------------------------------------
# Service Account for VM
# -----------------------------------------------------------------------------

resource "google_service_account" "vm" {
  account_id   = "${var.app_name}-vm-sa"
  display_name = "${var.app_name} VM Service Account"
  description  = "Service account for ${var.app_name} Compute Engine VM with minimal permissions"
}

# -----------------------------------------------------------------------------
# IAM Role Bindings - Minimal Permissions
# -----------------------------------------------------------------------------

# Artifact Registry Reader - Pull Docker images
resource "google_project_iam_member" "vm_artifact_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.vm.email}"
}

# Cloud SQL Client - Connect to Cloud SQL
resource "google_project_iam_member" "vm_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.vm.email}"
}

# Logging Writer - Write logs to Cloud Logging
resource "google_project_iam_member" "vm_logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.vm.email}"
}

# Monitoring Metric Writer - Send metrics to Cloud Monitoring
resource "google_project_iam_member" "vm_monitoring_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.vm.email}"
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "vm_service_account" {
  value       = google_service_account.vm.email
  description = "Email of the VM service account"
}

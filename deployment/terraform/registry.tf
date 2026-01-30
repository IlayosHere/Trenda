# ============================================================================
# Artifact Registry Configuration
# Docker container image repository
# ============================================================================

resource "google_artifact_registry_repository" "main" {
  location      = var.region
  repository_id = "${var.app_name}-docker"
  description   = "Docker repository for ${var.app_name} container images"
  format        = "DOCKER"

  # Cleanup policy - keep last 10 versions
  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-minimum-versions"
    action = "KEEP"

    most_recent_versions {
      keep_count = 10
    }
  }

  cleanup_policies {
    id     = "delete-old-images"
    action = "DELETE"

    condition {
      older_than = "2592000s" # 30 days
    }
  }
}

# Output the registry URL for use in deployment scripts
output "registry_url" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}"
  description = "Docker registry URL for pushing images"
}

output "docker_image_url" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}/${var.app_name}:${var.docker_image_tag}"
  description = "Full Docker image URL including tag"
}

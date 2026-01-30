# ============================================================================
# Terraform Outputs
# Key information about deployed infrastructure
# ============================================================================

# -----------------------------------------------------------------------------
# Summary Output
# -----------------------------------------------------------------------------

output "deployment_summary" {
  value = <<-EOF
    ============================================
    Trenda MT5 Trading Bot - Deployment Summary
    ============================================
    
    Project:     ${var.project_id}
    Region:      ${var.region}
    Environment: ${var.environment}
    
    VM Instance:
      Name:        ${google_compute_instance.app_server.name}
      Internal IP: ${google_compute_instance.app_server.network_interface[0].network_ip}
      Type:        ${var.vm_machine_type}
    
    Database:
      Instance:   ${google_sql_database_instance.postgres_instance.name}
      Private IP: ${google_sql_database_instance.postgres_instance.private_ip_address}
      Database:   ${var.db_name}
      User:       ${var.db_user}
    
    Docker Registry:
      URL: ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}
    
    SSH Access:
      gcloud compute ssh ${google_compute_instance.app_server.name} --zone=${var.zone} --tunnel-through-iap
    
    ============================================
  EOF
  description = "Summary of deployed resources"
}

# -----------------------------------------------------------------------------
# Database Connection Details
# -----------------------------------------------------------------------------

output "database_connection" {
  value = {
    host     = google_sql_database_instance.postgres_instance.private_ip_address
    port     = 5432
    database = var.db_name
    user     = var.db_user
  }
  description = "Database connection details (password excluded)"
}

output "database_private_ip" {
  value       = google_sql_database_instance.postgres_instance.private_ip_address
  description = "Private IP address of Cloud SQL instance"
}

output "database_connection_name" {
  value       = google_sql_database_instance.postgres_instance.connection_name
  description = "Cloud SQL connection name for Cloud SQL Proxy"
}

# -----------------------------------------------------------------------------
# Network Details
# -----------------------------------------------------------------------------

output "vpc_network" {
  value       = google_compute_network.vpc_network.name
  description = "VPC network name"
}

output "subnet" {
  value       = google_compute_subnetwork.private_subnet.name
  description = "Private subnet name"
}

output "subnet_cidr" {
  value       = google_compute_subnetwork.private_subnet.ip_cidr_range
  description = "Private subnet CIDR range"
}

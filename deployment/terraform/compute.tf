resource "google_compute_instance" "app_server" {
  name         = "${var.app_name}-vm-${var.environment}"
  machine_type = var.vm_machine_type
  zone         = var.zone

  tags = ["${var.app_name}-vm"]

  boot_disk {
    initialize_params {
      image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
      size  = var.vm_disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.private_subnet.id
  }

  service_account {
    email  = google_service_account.app_sa.email
    scopes = ["cloud-platform"]
  }

  metadata_startup_script = <<-SCRIPT
    #!/bin/bash
    set -e
    apt-get update -y
    if ! command -v docker &> /dev/null; then
      apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
      echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
      apt-get update -y
      apt-get install -y docker-ce docker-ce-cli containerd.io
      systemctl enable docker
      systemctl start docker
    fi
    gcloud auth configure-docker ${var.region}-docker.pkg.dev --quiet
    DOCKER_IMAGE="${var.region}-docker.pkg.dev/${var.project_id}/${var.app_name}-docker/${var.app_name}:${var.docker_image_tag}"
    docker pull $DOCKER_IMAGE
    docker stop ${var.app_name} 2>/dev/null || true
    docker rm ${var.app_name} 2>/dev/null || true
    docker run -d \
      --name ${var.app_name} \
      --restart unless-stopped \
      -p ${var.app_port}:${var.app_port} \
      -e DB_HOST="${google_sql_database_instance.postgres_instance.private_ip_address}" \
      -e DB_PORT="5432" \
      -e DB_NAME="${var.db_name}" \
      -e DB_USER="${var.db_user}" \
      -e DB_PASSWORD="${var.db_password}" \
      -e RUN_MODE="${var.run_mode}" \
      -e MT5_LOGIN="${var.mt5_login}" \
      -e MT5_PASSWORD="${var.mt5_password}" \
      -e MT5_SERVER="${var.mt5_server}" \
      $DOCKER_IMAGE
  SCRIPT

  metadata = {
    startup-script-hash = md5("${var.docker_image_tag}-${var.run_mode}")
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                  = true
    enable_integrity_monitoring = true
  }

  allow_stopping_for_update = true

  depends_on = [
    google_sql_database_instance.postgres_instance,
    google_artifact_registry_repository.main
  ]
}

output "vm_internal_ip" {
  value = google_compute_instance.app_server.network_interface[0].network_ip
}

output "vm_name" {
  value = google_compute_instance.app_server.name
}

output "ssh_command" {
  value = "gcloud compute ssh ${google_compute_instance.app_server.name} --zone=${var.zone} --tunnel-through-iap"
}
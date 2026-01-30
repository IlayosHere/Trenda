# ============================================================================
# VPC Network Configuration
# Private subnet with Cloud NAT for secure outbound internet access
# ============================================================================

# -----------------------------------------------------------------------------
# VPC Network
# -----------------------------------------------------------------------------

resource "google_compute_network" "main" {
  name                    = "${var.app_name}-vpc"
  auto_create_subnetworks = false
  description             = "Main VPC network for ${var.app_name}"
}

# -----------------------------------------------------------------------------
# Private Subnet
# -----------------------------------------------------------------------------

resource "google_compute_subnetwork" "private" {
  name                     = "${var.app_name}-private-subnet"
  ip_cidr_range            = var.subnet_cidr
  region                   = var.region
  network                  = google_compute_network.main.id
  private_ip_google_access = true

  description = "Private subnet for ${var.app_name} resources"
}

# -----------------------------------------------------------------------------
# Cloud Router (required for Cloud NAT)
# -----------------------------------------------------------------------------

resource "google_compute_router" "main" {
  name    = "${var.app_name}-router"
  network = google_compute_network.main.id
  region  = var.region

  description = "Cloud Router for NAT gateway"
}

# -----------------------------------------------------------------------------
# Cloud NAT - Provides outbound internet access without public IPs
# -----------------------------------------------------------------------------

resource "google_compute_router_nat" "main" {
  name   = "${var.app_name}-nat"
  router = google_compute_router.main.name
  region = var.region

  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# -----------------------------------------------------------------------------
# Firewall Rules
# -----------------------------------------------------------------------------

# Allow SSH access (for debugging/maintenance)
resource "google_compute_firewall" "allow_ssh" {
  name    = "${var.app_name}-allow-ssh"
  network = google_compute_network.main.id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["${var.app_name}-vm"]

  description = "Allow SSH access to VMs"
}

# Allow application port
resource "google_compute_firewall" "allow_app" {
  name    = "${var.app_name}-allow-app"
  network = google_compute_network.main.id

  allow {
    protocol = "tcp"
    ports    = [tostring(var.app_port)]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["${var.app_name}-vm"]

  description = "Allow application port ${var.app_port} access"
}

# Allow internal communication within VPC
resource "google_compute_firewall" "allow_internal" {
  name    = "${var.app_name}-allow-internal"
  network = google_compute_network.main.id

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "icmp"
  }

  source_ranges = [var.subnet_cidr]

  description = "Allow all internal traffic within VPC"
}

# Allow health checks from GCP
resource "google_compute_firewall" "allow_health_check" {
  name    = "${var.app_name}-allow-health-check"
  network = google_compute_network.main.id

  allow {
    protocol = "tcp"
    ports    = [tostring(var.app_port)]
  }

  # GCP health check IP ranges
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  target_tags   = ["${var.app_name}-vm"]

  description = "Allow GCP health checks"
}

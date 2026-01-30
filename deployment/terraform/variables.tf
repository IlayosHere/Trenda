# ============================================================================
# Terraform Variables
# All configurable values for the GCP infrastructure
# ============================================================================

# -----------------------------------------------------------------------------
# Project Configuration
# -----------------------------------------------------------------------------

variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "project-442a2741-f823-4e42-814"
}

variable "region" {
  description = "GCP Region for resources"
  type        = string
  default     = "me-west1"
}

variable "zone" {
  description = "GCP Zone for compute resources"
  type        = string
  default     = "me-west1-a"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"
}

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "trenda"
}

variable "app_port" {
  description = "Port the application listens on"
  type        = number
  default     = 8001
}

variable "docker_image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

# -----------------------------------------------------------------------------
# Database Configuration
# -----------------------------------------------------------------------------

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "trenda"
}

variable "db_user" {
  description = "PostgreSQL database user"
  type        = string
  default     = "trenda_app"
}

variable "db_password" {
  description = "PostgreSQL database password"
  type        = string
  sensitive   = true
}

variable "db_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-f1-micro"
}

variable "db_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "POSTGRES_15"
}

# -----------------------------------------------------------------------------
# Compute Configuration
# -----------------------------------------------------------------------------

variable "vm_machine_type" {
  description = "GCE machine type"
  type        = string
  default     = "e2-medium"
}

variable "vm_disk_size_gb" {
  description = "Boot disk size in GB"
  type        = number
  default     = 30
}

# -----------------------------------------------------------------------------
# Network Configuration
# -----------------------------------------------------------------------------

variable "subnet_cidr" {
  description = "CIDR range for the private subnet"
  type        = string
  default     = "10.0.1.0/24"
}

# -----------------------------------------------------------------------------
# MT5 Configuration
# -----------------------------------------------------------------------------

variable "mt5_login" {
  description = "MetaTrader 5 account login"
  type        = string
  default     = ""
  sensitive   = true
}

variable "mt5_password" {
  description = "MetaTrader 5 account password"
  type        = string
  default     = ""
  sensitive   = true
}

variable "mt5_server" {
  description = "MetaTrader 5 broker server"
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# Run Mode
# -----------------------------------------------------------------------------

variable "run_mode" {
  description = "Application run mode: replay or live"
  type        = string
  default     = "live"

  validation {
    condition     = contains(["replay", "live"], var.run_mode)
    error_message = "run_mode must be either 'replay' or 'live'."
  }
}

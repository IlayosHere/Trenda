# ============================================================================
# Trenda MT5 Trading Bot - One-Click Deployment Script (PowerShell)
# ============================================================================
#
# This script performs:
# 1. Creates GCS bucket for Terraform state (if not exists)
# 2. Builds and pushes Docker image to Artifact Registry
# 3. Runs terraform init and terraform apply
#
# Prerequisites:
# - Google Cloud SDK (gcloud) installed and configured
# - Docker Desktop running
# - Terraform CLI installed
# - Authenticated with GCP: gcloud auth application-default login
#
# ============================================================================

param(
    [string]$Environment = "prod",
    [string]$ImageTag = "latest",
    [switch]$SkipBuild,
    [switch]$SkipTerraform,
    [switch]$PlanOnly,
    [switch]$Destroy
)

$ErrorActionPreference = "Stop"

# Configuration
$PROJECT_ID = "project-442a2741-f823-4e42-814"
$REGION = "me-west1"
$APP_NAME = "trenda"
$STATE_BUCKET = "trenda-terraform-state"

# Paths
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$TERRAFORM_DIR = Join-Path $SCRIPT_DIR "terraform"
$DATA_RETRIEVER_DIR = Join-Path (Split-Path -Parent $SCRIPT_DIR) "data-retriever"

# Colors for output
function Write-Step { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Failure { param($msg) Write-Host "    [ERROR] $msg" -ForegroundColor Red }

# Banner
Write-Host @"
============================================
 Trenda MT5 Trading Bot - Deployment
============================================
 Project:     $PROJECT_ID
 Region:      $REGION
 Environment: $Environment
 Image Tag:   $ImageTag
============================================
"@ -ForegroundColor Magenta

# ============================================================================
# Step 1: Verify Prerequisites
# ============================================================================

Write-Step "Verifying prerequisites..."

# Check gcloud
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Failure "gcloud CLI not found. Please install Google Cloud SDK."
    exit 1
}
Write-Success "gcloud CLI found"

# Check Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Failure "Docker not found. Please install Docker Desktop."
    exit 1
}
Write-Success "Docker found"

# Check Terraform
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Write-Failure "Terraform not found. Please install Terraform CLI."
    exit 1
}
Write-Success "Terraform found"

# Verify GCP authentication
$gcloudAccount = gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>$null
if (-not $gcloudAccount) {
    Write-Failure "Not authenticated with GCP. Run: gcloud auth application-default login"
    exit 1
}
Write-Success "Authenticated as: $gcloudAccount"

# Set project
gcloud config set project $PROJECT_ID 2>$null

# ============================================================================
# Step 2: Create GCS Bucket for Terraform State
# ============================================================================

Write-Step "Setting up Terraform state bucket..."

$bucketExists = gsutil ls -b "gs://$STATE_BUCKET" 2>$null
if ($bucketExists) {
    Write-Success "State bucket already exists: gs://$STATE_BUCKET"
} else {
    Write-Host "    Creating state bucket..."
    gsutil mb -p $PROJECT_ID -l $REGION -b on "gs://$STATE_BUCKET"
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Failed to create state bucket"
        exit 1
    }
    
    # Enable versioning for state protection
    gsutil versioning set on "gs://$STATE_BUCKET"
    Write-Success "Created state bucket: gs://$STATE_BUCKET"
}

# ============================================================================
# Step 3: Enable Required GCP APIs
# ============================================================================

Write-Step "Enabling required GCP APIs..."

$requiredAPIs = @(
    "compute.googleapis.com",
    "sqladmin.googleapis.com",
    "artifactregistry.googleapis.com",
    "servicenetworking.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com"
)

foreach ($api in $requiredAPIs) {
    gcloud services enable $api --quiet 2>$null
    Write-Success "Enabled: $api"
}

# ============================================================================
# Step 4: Build and Push Docker Image
# ============================================================================

if (-not $SkipBuild) {
    Write-Step "Building and pushing Docker image..."
    
    $REGISTRY_URL = "$REGION-docker.pkg.dev/$PROJECT_ID/$APP_NAME-docker"
    $IMAGE_URL = "$REGISTRY_URL/$APP_NAME`:$ImageTag"
    
    # Configure Docker for Artifact Registry
    Write-Host "    Configuring Docker authentication..."
    gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
    
    # Create Artifact Registry if it doesn't exist (handled by Terraform, but create early)
    $repoExists = gcloud artifacts repositories describe "$APP_NAME-docker" --location=$REGION 2>$null
    if (-not $repoExists) {
        Write-Host "    Creating Artifact Registry repository..."
        gcloud artifacts repositories create "$APP_NAME-docker" `
            --repository-format=docker `
            --location=$REGION `
            --description="Docker repository for $APP_NAME" `
            --quiet
    }
    
    # Build Docker image
    Write-Host "    Building Docker image..."
    $PROJECT_ROOT = Split-Path -Parent $SCRIPT_DIR
    Push-Location $PROJECT_ROOT
    docker build -t $IMAGE_URL -f deployment/Dockerfile .
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Docker build failed"
        Pop-Location
        exit 1
    }
    Pop-Location
    Write-Success "Built: $IMAGE_URL"
    
    # Push Docker image
    Write-Host "    Pushing Docker image..."
    docker push $IMAGE_URL
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Docker push failed"
        exit 1
    }
    Write-Success "Pushed: $IMAGE_URL"
} else {
    Write-Warning "Skipping Docker build (--SkipBuild)"
}

# ============================================================================
# Step 5: Run Terraform
# ============================================================================

if (-not $SkipTerraform) {
    Write-Step "Running Terraform..."
    
    Push-Location $TERRAFORM_DIR
    
    # Check for terraform.tfvars
    if (-not (Test-Path "terraform.tfvars")) {
        Write-Warning "terraform.tfvars not found!"
        Write-Host "    Please copy terraform.tfvars.example to terraform.tfvars and configure:"
        Write-Host "    - db_password: Set a secure database password"
        Write-Host "    - mt5_login, mt5_password, mt5_server: Your MT5 credentials"
        Pop-Location
        exit 1
    }
    
    # Terraform init
    Write-Host "    Running terraform init..."
    terraform init
    if ($LASTEXITCODE -ne 0) {
        Write-Failure "Terraform init failed"
        Pop-Location
        exit 1
    }
    Write-Success "Terraform initialized"
    
    if ($Destroy) {
        # Terraform destroy
        Write-Warning "DESTROYING infrastructure..."
        terraform destroy -var="docker_image_tag=$ImageTag"
    } elseif ($PlanOnly) {
        # Terraform plan only
        Write-Host "    Running terraform plan..."
        terraform plan -var="docker_image_tag=$ImageTag"
    } else {
        # Terraform apply
        Write-Host "    Running terraform apply..."
        terraform apply -var="docker_image_tag=$ImageTag" -auto-approve
        if ($LASTEXITCODE -ne 0) {
            Write-Failure "Terraform apply failed"
            Pop-Location
            exit 1
        }
        Write-Success "Infrastructure deployed successfully!"
        
        # Show outputs
        Write-Host "`n"
        terraform output deployment_summary
    }
    
    Pop-Location
} else {
    Write-Warning "Skipping Terraform (--SkipTerraform)"
}

# ============================================================================
# Deployment Complete
# ============================================================================

Write-Host @"

============================================
 Deployment Complete!
============================================
 
 Next Steps:
 1. SSH into VM: gcloud compute ssh $APP_NAME-vm-$Environment --zone=$REGION-a --tunnel-through-iap
 2. Check container logs: docker logs $APP_NAME
 3. View in Console: https://console.cloud.google.com/compute/instances?project=$PROJECT_ID

============================================
"@ -ForegroundColor Green

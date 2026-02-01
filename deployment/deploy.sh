#!/bin/bash
# ============================================================================
# Trenda MT5 Trading Bot - One-Click Deployment Script (Bash)
# ============================================================================
#
# This script performs:
# 1. Creates GCS bucket for Terraform state (if not exists)
# 2. Builds and pushes Docker image to Artifact Registry
# 3. Runs terraform init and terraform apply
#
# Prerequisites:
# - Google Cloud SDK (gcloud) installed and configured
# - Docker installed and running
# - Terraform CLI installed
# - Authenticated with GCP: gcloud auth application-default login
#
# Usage:
#   ./deploy.sh [options]
#
# Options:
#   --env=<environment>    Environment name (default: prod)
#   --tag=<image_tag>      Docker image tag (default: latest)
#   --skip-build           Skip Docker build/push
#   --skip-terraform       Skip Terraform apply
#   --plan-only            Only run terraform plan
#   --destroy              Destroy infrastructure
#
# ============================================================================

set -e

# Configuration
PROJECT_ID="project-442a2741-f823-4e42-814"
REGION="me-west1"
APP_NAME="trenda"
STATE_BUCKET="trenda-terraform-state"

# Defaults
ENVIRONMENT="prod"
IMAGE_TAG="latest"
SKIP_BUILD=false
SKIP_TERRAFORM=false
PLAN_ONLY=false
DESTROY=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --env=*)
            ENVIRONMENT="${arg#*=}"
            ;;
        --tag=*)
            IMAGE_TAG="${arg#*=}"
            ;;
        --skip-build)
            SKIP_BUILD=true
            ;;
        --skip-terraform)
            SKIP_TERRAFORM=true
            ;;
        --plan-only)
            PLAN_ONLY=true
            ;;
        --destroy)
            DESTROY=true
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/terraform"
DATA_RETRIEVER_DIR="$(dirname "$SCRIPT_DIR")/data-retriever"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Helper functions
step()    { echo -e "\n${CYAN}==> $1${NC}"; }
success() { echo -e "    ${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "    ${YELLOW}[WARN]${NC} $1"; }
fail()    { echo -e "    ${RED}[ERROR]${NC} $1"; exit 1; }

# Banner
echo -e "${MAGENTA}"
cat << 'EOF'
============================================
 Trenda MT5 Trading Bot - Deployment
============================================
EOF
echo " Project:     $PROJECT_ID"
echo " Region:      $REGION"
echo " Environment: $ENVIRONMENT"
echo " Image Tag:   $IMAGE_TAG"
echo "============================================"
echo -e "${NC}"

# ============================================================================
# Step 1: Verify Prerequisites
# ============================================================================

step "Verifying prerequisites..."

# Check gcloud
if ! command -v gcloud &> /dev/null; then
    fail "gcloud CLI not found. Please install Google Cloud SDK."
fi
success "gcloud CLI found"

# Check Docker
if ! command -v docker &> /dev/null; then
    fail "Docker not found. Please install Docker."
fi
success "Docker found"

# Check Terraform
if ! command -v terraform &> /dev/null; then
    fail "Terraform not found. Please install Terraform CLI."
fi
success "Terraform found"

# Verify GCP authentication
GCLOUD_ACCOUNT=$(gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>/dev/null || true)
if [ -z "$GCLOUD_ACCOUNT" ]; then
    fail "Not authenticated with GCP. Run: gcloud auth application-default login"
fi
success "Authenticated as: $GCLOUD_ACCOUNT"

# Set project
gcloud config set project "$PROJECT_ID" 2>/dev/null

# ============================================================================
# Step 2: Create GCS Bucket for Terraform State
# ============================================================================

step "Setting up Terraform state bucket..."

if gsutil ls -b "gs://$STATE_BUCKET" &> /dev/null; then
    success "State bucket already exists: gs://$STATE_BUCKET"
else
    echo "    Creating state bucket..."
    gsutil mb -p "$PROJECT_ID" -l "$REGION" -b on "gs://$STATE_BUCKET"
    
    # Enable versioning for state protection
    gsutil versioning set on "gs://$STATE_BUCKET"
    success "Created state bucket: gs://$STATE_BUCKET"
fi

# ============================================================================
# Step 3: Enable Required GCP APIs
# ============================================================================

step "Enabling required GCP APIs..."

REQUIRED_APIS=(
    "compute.googleapis.com"
    "sqladmin.googleapis.com"
    "artifactregistry.googleapis.com"
    "servicenetworking.googleapis.com"
    "cloudresourcemanager.googleapis.com"
    "iam.googleapis.com"
)

for api in "${REQUIRED_APIS[@]}"; do
    gcloud services enable "$api" --quiet 2>/dev/null
    success "Enabled: $api"
done

# ============================================================================
# Step 4: Build and Push Docker Image
# ============================================================================

if [ "$SKIP_BUILD" = false ]; then
    step "Building and pushing Docker image..."
    
    REGISTRY_URL="$REGION-docker.pkg.dev/$PROJECT_ID/$APP_NAME-docker"
    IMAGE_URL="$REGISTRY_URL/$APP_NAME:$IMAGE_TAG"
    
    # Configure Docker for Artifact Registry
    echo "    Configuring Docker authentication..."
    gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
    
    # Create Artifact Registry if it doesn't exist
    if ! gcloud artifacts repositories describe "$APP_NAME-docker" --location="$REGION" &> /dev/null; then
        echo "    Creating Artifact Registry repository..."
        gcloud artifacts repositories create "$APP_NAME-docker" \
            --repository-format=docker \
            --location="$REGION" \
            --description="Docker repository for $APP_NAME" \
            --quiet
    fi
    
    # Build Docker image
    echo "    Building Docker image..."
    cd "$(dirname "$SCRIPT_DIR")"  # Go to project root
    docker build -t "$IMAGE_URL" -f deployment/Dockerfile .
    success "Built: $IMAGE_URL"
    
    # Push Docker image
    echo "    Pushing Docker image..."
    docker push "$IMAGE_URL"
    success "Pushed: $IMAGE_URL"
else
    warn "Skipping Docker build (--skip-build)"
fi

# ============================================================================
# Step 5: Run Terraform
# ============================================================================

if [ "$SKIP_TERRAFORM" = false ]; then
    step "Running Terraform..."
    
    cd "$TERRAFORM_DIR"
    
    # Check for terraform.tfvars
    if [ ! -f "terraform.tfvars" ]; then
        warn "terraform.tfvars not found!"
        echo "    Please copy terraform.tfvars.example to terraform.tfvars and configure:"
        echo "    - db_password: Set a secure database password"
        echo "    - mt5_login, mt5_password, mt5_server: Your MT5 credentials"
        exit 1
    fi
    
    # Terraform init
    echo "    Running terraform init..."
    terraform init
    success "Terraform initialized"
    
    if [ "$DESTROY" = true ]; then
        # Terraform destroy
        warn "DESTROYING infrastructure..."
        terraform destroy -var="docker_image_tag=$IMAGE_TAG"
    elif [ "$PLAN_ONLY" = true ]; then
        # Terraform plan only
        echo "    Running terraform plan..."
        terraform plan -var="docker_image_tag=$IMAGE_TAG"
    else
        # Terraform apply
        echo "    Running terraform apply..."
        terraform apply -var="docker_image_tag=$IMAGE_TAG" -auto-approve
        success "Infrastructure deployed successfully!"
        
        # Show outputs
        echo ""
        terraform output deployment_summary
    fi
else
    warn "Skipping Terraform (--skip-terraform)"
fi

# ============================================================================
# Deployment Complete
# ============================================================================

echo -e "${GREEN}"
cat << EOF

============================================
 Deployment Complete!
============================================
 
 Next Steps:
 1. SSH into VM: gcloud compute ssh $APP_NAME-vm-$ENVIRONMENT --zone=${REGION}-a --tunnel-through-iap
 2. Check container logs: docker logs $APP_NAME
 3. View in Console: https://console.cloud.google.com/compute/instances?project=$PROJECT_ID

============================================
EOF
echo -e "${NC}"

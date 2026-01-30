# ============================================================================
# Trenda - Production Variables
# ============================================================================

# GCP Project Configuration
project_id  = "project-442a2741-f823-4e42-814"
region      = "me-west1"
zone        = "me-west1-a"
environment = "prod"

# Application Configuration
app_name         = "trenda"
app_port         = 8001
docker_image_tag = "latest"

# Database Configuration
# שים לב: שיניתי את המשתמש ל-postgres כפי שמופיע ב-ENV שלך
db_name     = "trenda"
db_user     = "postgres"
db_password = "trenda123" 
db_tier     = "db-f1-micro"
db_version  = "POSTGRES_15"

# Compute Configuration
vm_machine_type = "e2-medium"
vm_disk_size_gb = 30

# Network Configuration
subnet_cidr = "10.0.1.0/24"

# MT5 Configuration
# כאן אתה צריך להשלים את פרטי החשבון האמיתיים שלך ב-Pepperstone
mt5_login    = "61457345"   
mt5_password = "Treanda123!"
mt5_server   = "Pepperstone-MT5-Live" # או השרת שקיבלת מהברוקר

# Run Mode
run_mode = "live"
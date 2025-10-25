import os

# Read OANDA credentials from environment variables for security
# Provide defaults for local development if needed, but environment variables are safer.

OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "YOUR_OANDA_ACCOUNT_ID")
OANDA_ACCESS_TOKEN = os.environ.get("OANDA_ACCESS_TOKEN", "YOUR_OANDA_ACCESS_TOKEN")

# Specify the OANDA environment: 'practice' or 'live'
OANDA_ENVIRONMENT = os.environ.get("OANDA_ENVIRONMENT", "practice")
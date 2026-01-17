"""
Trenda REST API (Controller Layer)

Handles incoming HTTP requests, validates inputs (if any),
delegates business logic processing to the service layer,
and constructs appropriate HTTP responses based on service outcomes.
Loads configuration from environment variables (via .env file).
"""
import os
from service import get_trend_data_service, get_aoi_data_service
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status # Import status codes
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
from typing import List, Dict, Any, Optional

# --- Load Environment Variables ---
# Ensures .env is loaded BEFORE other modules that might need env vars
# Place .env file in the root directory where uvicorn is run
load_dotenv()

# --- Setup Logging ---
# Configure basic logging for the API application
from logger import get_logger
logger = get_logger(__name__) # Get logger for this module

# --- FastAPI App Initialization ---
# Create the main FastAPI application instance
app = FastAPI(
    title="Trenda API",
    description="Provides Forex trend analysis data based on the Snake-Line strategy.",
    version="1.0.0",
    # Optional: Customize documentation URLs
    # docs_url="/api/v1/docs",
    # redoc_url="/api/v1/redoc",
    # openapi_url="/api/v1/openapi.json"
)

# --- Middleware ---

# CORS Middleware (Cross-Origin Resource Sharing)
# Allows frontend applications hosted on different domains/ports to access this API.
# Read allowed origins from environment variable, default to common dev origins.
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8080")
origins = [origin.strip() for origin in allowed_origins_str.split(',') if origin.strip()]
logger.info(f"Configuring CORS middleware for allowed origins: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # List of allowed origins
    allow_credentials=True,    # Allow cookies if needed later
    allow_methods=["GET"],       # Only allow GET requests for this API
    allow_headers=["*"],       # Allow all standard headers
)


# Define response model using generic List[Dict] for simplicity
# For more robustness, define a Pydantic model representing the Trend data structure
TrendResponseModel = Optional[List[Dict[str, Any]]]

@app.get("/trends",
         response_model=TrendResponseModel, # Validate and document the response structure
         tags=["Trends"])
async def get_trends():
    logger.info("Handling incoming request for /trends endpoint.")
    try:
        data = get_trend_data_service()
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No trend data available.",
            )

        return data

    except HTTPException as http_exc:
        # Re-raise exceptions already formatted for HTTP (e.g., from potential input validation later)
        logger.warning(f"HTTP exception during /trends request: {http_exc.detail} (Status: {http_exc.status_code})")
        raise http_exc
    except Exception as e:
        # Catch any other unexpected errors within this endpoint handler
        logger.error(f"Unexpected error in /trends endpoint handler: {e}", exc_info=True) # Log full traceback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred."
        )


@app.get(
    "/aoi/{symbol}",
    response_model=Dict[str, Any],
    tags=["Areas of Interest"],
)
async def get_aoi(symbol: str):
    """Retrieve area of interest details for the requested forex symbol."""

    logger.info("Handling incoming request for /aoi/%s endpoint.", symbol)
    try:
        data = get_aoi_data_service(symbol)
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No AOI data found for symbol '{symbol}'.",
            )

        return data

    except HTTPException as http_exc:
        logger.warning(
            "HTTP exception during /aoi/%s request: %s (Status: %s)",
            symbol,
            http_exc.detail,
            http_exc.status_code,
        )
        raise http_exc
    except Exception as e:
        logger.error(
            "Unexpected error in /aoi/%s endpoint handler: %s",
            symbol,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred.",
        )

# --- How to Run the API Server (Development) ---
# 1. Ensure PostgreSQL is running.
# 2. Ensure your bot (`main.py`) has run at least once or the DB is populated.
# 3. Create a `.env` file in the project root with `DB_PASSWORD` etc.
# 4. In a terminal in the project root:
#    uvicorn api:app --reload --host 0.0.0.0 --port 8000
#
#    Access API docs at http://127.0.0.1:8000/docs
#    Access trend data at http://127.0.0.1:8000/trends
"""FastAPI application exposing trend data endpoints."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, status

from .config import get_api_config
from .logging_config import get_logger
from .models import AreaOfInterestResponse, TrendResponse
from .services.trends import get_aoi, get_trends
from fastapi.middleware.cors import CORSMiddleware

log = get_logger(__name__)
app = FastAPI(
    title="Trenda API",
    description="Provides Forex trend analysis data based on the Snake-Line strategy.",
    version="1.0.0",
)

config = get_api_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/trends", response_model=TrendResponse, tags=["Trends"])
async def read_trends() -> TrendResponse:
    log.info("Handling incoming request for /trends endpoint")

    payload = get_trends()
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No trend data available.",
        )
    return payload


@app.get("/aoi/{symbol}", response_model=AreaOfInterestResponse, tags=["Areas of Interest"])
async def read_area_of_interest(symbol: str) -> AreaOfInterestResponse:
    log.info("Handling incoming request for /aoi/%s endpoint", symbol)

    payload = get_aoi(symbol)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No AOI data found for symbol '{symbol}'.",
        )

    return payload

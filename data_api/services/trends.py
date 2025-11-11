"""Business logic for trend related operations."""
from __future__ import annotations

from typing import Optional

from ..logging_config import get_logger
from ..models import AreaOfInterestResponse, TrendResponse
from ..repositories.trends import fetch_all_trends, fetch_aoi

log = get_logger(__name__)

AOI_TIMEFRAME = "1H"


def get_trends() -> Optional[TrendResponse]:
    """Return all trend data ready for serialisation."""

    payload = fetch_all_trends()
    if payload is None:
        log.warning("Trend data fetch returned no results")
        return None

    return TrendResponse.parse_obj(payload)


def get_aoi(symbol: str) -> Optional[AreaOfInterestResponse]:
    """Return AOI details for the provided symbol."""

    payload = fetch_aoi(symbol, AOI_TIMEFRAME)
    if payload is None:
        log.info("No AOI data found for symbol '%s'", symbol)
        return None

    return AreaOfInterestResponse.parse_obj(payload)

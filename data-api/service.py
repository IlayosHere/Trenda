from typing import Optional, List, Dict, Any

# Import the repository functions
from repository import fetch_all_trend_data, fetch_aoi_for_symbol
from logger import get_logger

logger = get_logger(__name__)


AOI_HOUR_TIMEFRAME = "1H"


def get_trend_data_service() -> Optional[List[Dict[str, Any]]]:
    logger.info("Fetching trend data via repository...")
    data = fetch_all_trend_data()
    if data is None:
        logger.warning("Trend data fetch returned no results.")
        return None

    logger.info(f"Successfully retrieved data with {len(data)} records from repository.")
    return data


def get_aoi_data_service(symbol: str) -> Optional[Dict[str, Any]]:
    """Retrieve AOI information for the requested symbol using the 4H timeframe."""

    data = fetch_aoi_for_symbol(symbol)

    if data is None:
        return None

    logger.info(
        "Successfully retrieved %d AOI entries for symbol '%s' on timeframe '%s'",
        len(data.get("aois", [])),
        symbol,
        AOI_HOUR_TIMEFRAME,
    )
    return data

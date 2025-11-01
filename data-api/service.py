from typing import Optional, List, Dict, Any
import logging

# Import the repository functions
from repository import fetch_all_trend_data, fetch_aoi_for_symbol

log = logging.getLogger(__name__)
# Basic config if run standalone
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] API_Service: %(message)s')


FOUR_HOUR_TIMEFRAME = "4H"


def get_trend_data_service() -> Optional[List[Dict[str, Any]]]:
    log.info("Fetching trend data via repository...")
    data = fetch_all_trend_data()
    if data is None:
        log.warning("Trend data fetch returned no results.")
        return None

    log.info(f"Successfully retrieved data with {len(data)} records from repository.")
    return data


def get_aoi_data_service(symbol: str) -> Optional[Dict[str, Any]]:
    """Retrieve AOI information for the requested symbol using the 4H timeframe."""

    log.info("Fetching AOI data for symbol '%s' on timeframe '%s'", symbol, FOUR_HOUR_TIMEFRAME)
    data = fetch_aoi_for_symbol(symbol, FOUR_HOUR_TIMEFRAME)

    if data is None:
        log.info("No AOI data found for symbol '%s' on timeframe '%s'", symbol, FOUR_HOUR_TIMEFRAME)
        return None

    log.info(
        "Successfully retrieved %d AOI entries for symbol '%s' on timeframe '%s'",
        len(data.get("aois", [])),
        symbol,
        FOUR_HOUR_TIMEFRAME,
    )
    return data

from typing import Optional, List, Dict, Any
import logging

# Import the repository functions
from repository import fetch_all_trend_data

log = logging.getLogger(__name__)
# Basic config if run standalone
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] API_Service: %(message)s')


def get_trend_data_service() -> Optional[List[Dict[str, Any]]]:
    log.info("Fetching trend data via repository...")
    data = fetch_all_trend_data()
    log.info(f"Successfully retrieved data with {len(data)} records from repository.")
    return data
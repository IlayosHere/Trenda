import os
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

# Ensure environment variables are available when the module is imported.
load_dotenv()


class TwelveDataAPIError(Exception):
    """Raised when the Twelve Data API returns an unexpected response."""


TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TWELVE_DATA_BASE_URL = os.getenv("TWELVE_DATA_BASE_URL", "https://api.twelvedata.com")


def _format_symbol(symbol: str) -> str:
    """Convert an internal forex symbol to the Twelve Data format."""

    if "/" in symbol:
        return symbol.upper()

    cleaned = symbol.strip().upper()
    if len(cleaned) == 6:
        return f"{cleaned[:3]}/{cleaned[3:]}"

    return cleaned


def fetch_forex_candles(
    symbol: str, interval: str, lookback: int
) -> Optional[List[Dict[str, str]]]:
    """Fetch historical candles for a forex pair from Twelve Data.

    Args:
        symbol: Pair identifier (e.g., "EURUSD").
        interval: Twelve Data interval code (e.g., "1h", "1day").
        lookback: Number of candles to retrieve.

    Returns:
        A list of OHLC dictionaries ordered from most recent to oldest, or
        ``None`` if no data is available.

    Raises:
        TwelveDataAPIError: If the API key is missing or the request fails.
    """

    if not TWELVE_DATA_API_KEY:
        raise TwelveDataAPIError("TWELVE_DATA_API_KEY environment variable is not set.")

    params = {
        "symbol": _format_symbol(symbol),
        "interval": interval,
        "apikey": TWELVE_DATA_API_KEY,
        "outputsize": max(int(lookback), 1),
        "format": "JSON",
        "timezone": "UTC",
    }

    try:
        response = requests.get(
            f"{TWELVE_DATA_BASE_URL}/time_series", params=params, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as request_error:
        raise TwelveDataAPIError(
            f"Request to Twelve Data failed: {request_error}"
        ) from request_error

    payload = response.json()
    status = payload.get("status")

    if status == "error":
        message = payload.get("message", "Unknown error")
        code = payload.get("code")
        raise TwelveDataAPIError(f"Twelve Data error ({code}): {message}")

    values = payload.get("values")
    if not values:
        return None

    return values

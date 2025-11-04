import os
import time
from typing import Dict, Optional

import requests
from dotenv import load_dotenv

# Ensure environment variables are available when the module is imported.
load_dotenv()


class FinnhubAPIError(Exception):
    """Custom error raised when Finnhub returns an unexpected response."""


FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
FINNHUB_BASE_URL = os.getenv("FINNHUB_BASE_URL", "https://finnhub.io/api/v1")
FINNHUB_FX_EXCHANGE = os.getenv("FINNHUB_FX_EXCHANGE", "OANDA")


def _format_symbol(symbol: str) -> str:
    """Convert an internal forex symbol to the Finnhub format.

    Examples:
        "EURUSD" -> "OANDA:EUR_USD"
        "OANDA:EUR_USD" -> "OANDA:EUR_USD"
    """

    if ":" in symbol:
        return symbol

    cleaned = symbol.strip().upper()
    if len(cleaned) == 6:
        return f"{FINNHUB_FX_EXCHANGE}:{cleaned[:3]}_{cleaned[3:]}"

    return f"{FINNHUB_FX_EXCHANGE}:{cleaned}"


def fetch_forex_candles(
    symbol: str,
    resolution: str,
    lookback: int,
    seconds_per_candle: int,
) -> Optional[Dict[str, list]]:
    """Fetch historical candles for a forex pair from Finnhub.

    Args:
        symbol: Pair identifier (e.g., "EURUSD").
        resolution: Finnhub resolution code (e.g., "60", "D").
        lookback: Number of candles to retrieve.
        seconds_per_candle: Candle size in seconds.

    Returns:
        A dictionary with Finnhub candle arrays or ``None`` if no data.

    Raises:
        FinnhubAPIError: If the API key is missing or the request fails.
    """

    if not FINNHUB_API_KEY:
        raise FinnhubAPIError("FINNHUB_API_KEY environment variable is not set.")

    to_ts = int(time.time())
    from_ts = to_ts - max(lookback, 1) * seconds_per_candle

    params = {
        "symbol": _format_symbol(symbol),
        "resolution": resolution,
        "from": from_ts,
        "to": to_ts,
        "token": FINNHUB_API_KEY,
    }

    try:
        response = requests.get(
            f"{FINNHUB_BASE_URL}/forex/candle", params=params, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as request_error:
        raise FinnhubAPIError(
            f"Request to Finnhub failed: {request_error}"
        ) from request_error

    payload = response.json()
    status = payload.get("s")

    if status == "no_data":
        return None

    if status != "ok":
        raise FinnhubAPIError(f"Finnhub returned error status: {status}")

    # Finnhub returns arrays keyed by `o`, `h`, `l`, `c`, `v`, `t`.
    return {
        key: payload.get(key, [])
        for key in ("t", "o", "h", "l", "c", "v")
    }


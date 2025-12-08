from typing import Dict, List, Optional

import utils.display as display

from .db import (
    execute_many,
    execute_non_query,
    fetch_all,
    validate_aoi,
    validate_symbol,
    validate_timeframe,
)
from .queries import CLEAR_AOIS, FETCH_TRADABLE_AOIS, UPSERT_AOIS


def clear_aois(symbol: str, timeframe: str):
    normalized_symbol = validate_symbol(symbol)
    normalized_timeframe = validate_timeframe(timeframe)
    if not (normalized_symbol and normalized_timeframe):
        return

    execute_non_query(
        CLEAR_AOIS,
        (normalized_symbol, normalized_timeframe),
        context="clear_aois",
    )


def store_aois(
    symbol: str,
    timeframe: str,
    aois: List[Dict[str, float]],
) -> None:
    """Sync AOI zones for a forex pair/timeframe combination."""
    normalized_symbol = validate_symbol(symbol)
    normalized_timeframe = validate_timeframe(timeframe)
    if not (normalized_symbol and normalized_timeframe):
        return
    if not isinstance(aois, list):
        display.print_error("DB_VALIDATION: aois must be provided as a list")
        return

    param_sets = []
    for aoi in aois:
        if not isinstance(aoi, dict) or not validate_aoi(aoi):
            return
        aoi_type = aoi.get("type")
        if not isinstance(aoi_type, str) or not aoi_type:
            display.print_error("DB_VALIDATION: AOI type must be a non-empty string")
            return
        param_sets.append(
            (
                normalized_symbol,
                normalized_timeframe,
                aoi.get("lower_bound"),
                aoi.get("upper_bound"),
                aoi_type,
            )
        )

    if param_sets:
        execute_many(UPSERT_AOIS, param_sets, context="store_aois")


def fetch_tradable_aois(symbol: str) -> List[Dict[str, Optional[float]]]:
    normalized_symbol = validate_symbol(symbol)
    if not normalized_symbol:
        return []

    rows = fetch_all(
        FETCH_TRADABLE_AOIS,
        (normalized_symbol,),
        context="fetch_tradable_aois",
    )

    if not rows:
        return []

    return [
        {
            "lower_bound": float(row[0]) if row[0] is not None else None,
            "upper_bound": float(row[1]) if row[1] is not None else None,
        }
        for row in rows
    ]

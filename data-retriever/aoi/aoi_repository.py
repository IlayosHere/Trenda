from typing import List

from logger import get_logger

logger = get_logger(__name__)

from database.executor import DBExecutor
from database.queries import CLEAR_AOIS, FETCH_TRADABLE_AOIS, UPSERT_AOIS
from database.validation import DBValidator
from models import AOIZone


def clear_aois(symbol: str, timeframe: str):
    normalized_symbol = DBValidator.validate_symbol(symbol)
    normalized_timeframe = DBValidator.validate_timeframe(timeframe)
    if not (normalized_symbol and normalized_timeframe):
        return

    DBExecutor.execute_non_query(
        CLEAR_AOIS,
        (normalized_symbol, normalized_timeframe),
        context="clear_aois",
    )


def store_aois(
    symbol: str,
    timeframe: str,
    aois: List[AOIZone],
) -> None:
    """Sync AOI zones for a forex pair/timeframe combination."""
    normalized_symbol = DBValidator.validate_symbol(symbol)
    normalized_timeframe = DBValidator.validate_timeframe(timeframe)
    if not (normalized_symbol and normalized_timeframe):
        return
    param_sets = []
    for aoi in aois:
        if not DBValidator.validate_aoi(aoi):
            return
        aoi_type = aoi.classification
        if not isinstance(aoi_type, str) or not aoi_type:
            logger.error("DB_VALIDATION: AOI classification must be a non-empty string")
            return
        param_sets.append(
            (
                normalized_symbol,
                normalized_timeframe,
                aoi.lower,
                aoi.upper,
                aoi_type,
            )
        )

    if param_sets:
        DBExecutor.execute_many(UPSERT_AOIS, param_sets, context="store_aois")


def fetch_tradable_aois(symbol: str) -> List[AOIZone]:
    normalized_symbol = DBValidator.validate_symbol(symbol)
    if not normalized_symbol:
        return []

    rows = DBExecutor.fetch_all(
        FETCH_TRADABLE_AOIS,
        (normalized_symbol,),
        context="fetch_tradable_aois",
    )

    if not rows:
        return []

    zones: List[AOIZone] = []
    for row in rows:
        zone = AOIZone(
            lower=float(row[0]) if row[0] is not None else None,
            upper=float(row[1]) if row[1] is not None else None,
            timeframe=row[2] if len(row) > 2 else None,
            classification=row[3] if len(row) > 3 else "tradable",
        )
        if DBValidator.validate_aoi(zone):
            zones.append(zone)
    return zones


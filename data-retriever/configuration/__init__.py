from .database import POSTGRES_DB
from .forex_data import (
    FOREX_PAIRS,
    OANDA_INSTRUMENTS,
    TIMEFRAMES,
    OANDA_GRANULARITIES,
    ANALYSIS_PARAMS
)
from .scheduler import SCHEDULE_CONFIG
# <<< NEW >>>
from .api_keys import OANDA_ACCOUNT_ID, OANDA_ACCESS_TOKEN, OANDA_ENVIRONMENT

# Optionally define __all__ for explicit exports
__all__ = [
    "POSTGRES_DB",
    "FOREX_PAIRS",
    "OANDA_INSTRUMENTS",
    "TIMEFRAMES",
    "OANDA_GRANULARITIES",
    "ANALYSIS_PARAMS",
    "SCHEDULE_CONFIG",
    "OANDA_ACCOUNT_ID",
    "OANDA_ACCESS_TOKEN",
    "OANDA_ENVIRONMENT",
]
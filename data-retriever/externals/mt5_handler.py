try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
from logger import get_logger

logger = get_logger(__name__)


def initialize_mt5():
    """Initializes and checks the MT5 connection."""
    if mt5 is None:
        logger.warning("MetaTrader5 package not found. Skipping initialization.")
        return False
    if not mt5.initialize():
        logger.error(f"MT5 initialization failed. Error: {mt5.last_error()}")
        return False
    logger.info("✅ MT5 initialized successfully.")
    return True


def shutdown_mt5():
    if mt5 is not None:
        logger.info("Shutting down MT5 connection...")
        mt5.shutdown()


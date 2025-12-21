import MetaTrader5 as mt5
from utils.logger import get_logger

logger = get_logger(__name__)


def initialize_mt5():
    """Initializes and checks the MT5 connection."""
    if not mt5.initialize():
        logger.error(f"MT5 initialization failed. Error: {mt5.last_error()}")
        return False
    logger.info("✅ MT5 initialized successfully.")
    return True


def shutdown_mt5():
    logger.info("Shutting down MT5 connection...")
    mt5.shutdown()


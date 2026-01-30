import platform
import logging

logger = logging.getLogger(__name__)

# Determine the operating system
current_os = platform.system()

try:
    if current_os == 'Windows':
        # On Windows, use the native MetaTrader5 library
        import MetaTrader5 as mt5
        logger.info("Imported native MetaTrader5 for Windows.")
    else:
        # On Linux (or others), use the mt5linux library
        from mt5linux import MetaTrader5 as mt5
        logger.info(f"Imported mt5linux MetaTrader5 for {current_os}.")

except ImportError as e:
    logger.error(f"Failed to import MetaTrader5/mt5linux: {e}")
    mt5 = None

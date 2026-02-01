import platform
import logging

logger = logging.getLogger(__name__)

# Determine the operating system and initialize the MT5 bridge/module
current_os = platform.system()

try:
    if current_os == 'Windows':
        # On Windows, use the native MetaTrader5 library (already a module)
        import MetaTrader5 as mt5
        logger.info("Imported native MetaTrader5 for Windows.")
    else:
        # On Linux, use mt5linux bridge - MUST be instantiated as an object
        from mt5linux import MetaTrader5
        mt5 = MetaTrader5() # This creates the bridge instance
        logger.info(f"Initialized mt5linux bridge instance for {current_os}.")

except ImportError as e:
    logger.error(f"Failed to import MetaTrader5 or mt5linux: {e}")
    mt5 = None
except Exception as e:
    logger.error(f"Unexpected error during MT5 wrapper initialization: {e}")
    mt5 = None

import threading
from logger import get_logger

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logger = get_logger(__name__)

class MT5Connection:
    """Manages the lifecycle and thread-safety of the MetaTrader 5 connection."""
    
    def __init__(self):
        self._initialized = False
        self.lock = threading.RLock()
        self.mt5 = mt5

    def initialize(self) -> bool:
        """Initializes and checks the MT5 connection. Retries if connection is lost."""
        if self.mt5 is None:
            logger.warning("MetaTrader5 package not found. Skipping initialization.")
            return False
            
        with self.lock:
            try:
                # Even if initialized, check if terminal is actually connected and authorized
                if self._initialized:
                    terminal_info = self.mt5.terminal_info()
                    if terminal_info and terminal_info.connected:
                        return True
                    else:
                        logger.warning("MT5 terminal disconnected. Attempting re-initialization...")
                        self._initialized = False # Force re-init

                if not self.mt5.initialize():
                    logger.error(f"MT5 initialization failed. Error: {self.mt5.last_error()}")
                    return False
                
                # Additional check: terminal must be connected to a broker
                term_info = self.mt5.terminal_info()
                if not term_info or not term_info.connected:
                     logger.error("MT5 terminal initialized but not connected to server.")
                     return False

                logger.info("MT5 initialized and connected successfully.")
                self._initialized = True
                return True
            except Exception as e:
                logger.error(f"Critical error during MT5 initialization: {e}")
                return False

    def shutdown(self):
        """Shuts down the MT5 connection and resets state."""
        if self.mt5 is not None:
            with self.lock:
                logger.info("Shutting down MT5 connection...")
                self.mt5.shutdown()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

import time
import sys
from typing import Optional, Any
from logger import get_logger
from configuration.broker_config import (
    MT5_EMERGENCY_MAGIC_NUMBER, MT5_DEVIATION, MT5_CLOSE_RETRY_ATTEMPTS
)
from .safeguards import _trading_lock
from .types import CloseAttemptStatus

logger = get_logger(__name__)


class PositionCloser:
    """Handles position closing operations for MT5."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5

    def close_position(self, ticket: int) -> bool:
        """Closes an active position by its ticket ID with retry logic and verification."""
        if not self.connection.initialize():
            return False

        success = False
        for attempt in range(1, MT5_CLOSE_RETRY_ATTEMPTS + 1):
            status = self._attempt_close(ticket, attempt)
            if status.success:
                success = True
                break
            if not status.should_retry:
                return False
            
            logger.info(f"Retrying close for ticket {ticket} in 1s...")
            time.sleep(1)
        
        if not success:
            # All retry attempts exhausted - this is a critical failure
            error_message = f"Failed to close position {ticket} after {MT5_CLOSE_RETRY_ATTEMPTS} attempts"
            logger.critical(f"CRITICAL FAILURE: {error_message}")
            
            # Create lock file to prevent trading on restart
            try:
                _trading_lock.create_lock(error_message)
            except Exception as e:
                logger.critical(f"Failed to create lock file: {e}")
            
            # Shut down the entire system
            from system_shutdown import shutdown_system
            shutdown_system(error_message)
            
            return False

        return self._verify_closure(ticket)

    def _attempt_close(self, ticket: int, attempt: int) -> CloseAttemptStatus:
        """Performs a single closing attempt."""
        with self.connection.lock:
            pos = self._get_active_position(ticket)
            if not pos:
                if attempt == 1:
                    logger.warning(f"Close position {ticket}: Not found (already closed).")
                return CloseAttemptStatus(True, False)
            
            tick = self.mt5.symbol_info_tick(pos.symbol)
            if not tick:
                logger.error(f"Close attempt {attempt}: Failed to get tick for {pos.symbol}.")
                return CloseAttemptStatus(False, True)

            request = {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": self.mt5.ORDER_TYPE_SELL if pos.type == self.mt5.POSITION_TYPE_BUY else self.mt5.ORDER_TYPE_BUY,
                "position": ticket,
                "price": tick.bid if pos.type == self.mt5.POSITION_TYPE_BUY else tick.ask,
                "deviation": MT5_DEVIATION,
                "magic": MT5_EMERGENCY_MAGIC_NUMBER,
                "comment": "Auto-close",
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self.mt5.ORDER_FILLING_IOC,
            }
            
            result = self.mt5.order_send(request)

        # Safe attribute access: check if result has retcode before accessing
        if result and hasattr(result, 'retcode') and result.retcode == self.mt5.TRADE_RETCODE_DONE:
            return CloseAttemptStatus(True, False)
        
        # Safe access to retcode and last_error
        retcode = getattr(result, 'retcode', None) if result else None
        mt5_error = self.mt5.last_error() if hasattr(self.mt5, 'last_error') else "N/A"
        
        # Format error message safely, handling mock objects
        retcode_str = str(retcode) if retcode is not None else 'None'
        error_str = str(mt5_error) if mt5_error is not None else 'N/A'
        err_msg = f"Retcode: {retcode_str}, Error: {error_str}"
        
        if result and retcode == self.mt5.TRADE_RETCODE_FROZEN:
            logger.warning(f"Close attempt {attempt} for ticket {ticket}: Position is FROZEN. Retrying...")
        else:
            logger.error(f"Close attempt {attempt} failed for ticket {ticket}. {err_msg}")
        
        return CloseAttemptStatus(False, True)

    def _verify_closure(self, ticket: int) -> bool:
        """Final check to ensure the position is actually closed on the server."""
        time.sleep(0.5) 
        with self.connection.lock:
            if self._get_active_position(ticket):
                # Position still open after close signal - critical failure
                error_message = f"Position {ticket} still OPEN after close signal was confirmed"
                logger.critical(f"VERIFICATION FAILED: {error_message}")
                
                # Create lock file to prevent trading on restart
                try:
                    _trading_lock.create_lock(error_message)
                except Exception as e:
                    logger.critical(f"Failed to create lock file: {e}")
                
                # Shut down the entire system
                from system_shutdown import shutdown_system
                shutdown_system(error_message)
                
                return False

        logger.info(f"Position {ticket} closed and verified successfully.")
        return True

    def _get_active_position(self, ticket: int) -> Optional[Any]:
        """Helper to get a single active position by its unique ticket ID."""
        positions = self.mt5.positions_get(ticket=ticket)
        return positions[0] if positions else None

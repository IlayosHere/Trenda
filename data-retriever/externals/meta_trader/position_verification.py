from typing import Optional
from logger import get_logger
from configuration.broker_config import (
    MT5_SL_TP_THRESHOLD_MULTIPLIER, MT5_PRICE_THRESHOLD_FALLBACK,
    MT5_VERIFICATION_SLEEP, MT5_DEVIATION
)

logger = get_logger(__name__)


class PositionVerifier:
    """Handles position verification operations for MT5."""
    
    def __init__(self, connection, position_closer):
        self.connection = connection
        self.mt5 = connection.mt5
        self.position_closer = position_closer

    def verify_position_consistency(
        self, 
        ticket: int, 
        expected_sl: float, 
        expected_tp: float,
        expected_volume: float = 0.0,
        expected_price: float = 0.0
    ) -> bool:
        """Verifies that an open position's parameters match the requested values.
        
        This prevents hidden broker modifications (e.g., sliding SL/TP or filling 
        different volumes/prices) from going unnoticed.
        """
        if not self.connection.initialize():
            logger.error("Cannot verify position: MT5 initialization failed")
            return False  # Safer default: treat as unverified

        import time
        time.sleep(MT5_VERIFICATION_SLEEP) 
        
        with self.connection.lock:
            pos = self._get_active_position(ticket)
            if not pos:
                logger.warning(f"Verification: Position {ticket} not found (closed?).")
                return True

            sym_info = self.mt5.symbol_info(pos.symbol)
            point = sym_info.point if sym_info else 0.00001
            threshold = (point * MT5_SL_TP_THRESHOLD_MULTIPLIER) if sym_info else MT5_PRICE_THRESHOLD_FALLBACK
            
            # Capture all values atomically inside lock
            symbol_name = pos.symbol
            actual_sl, actual_tp = pos.sl, pos.tp
            actual_volume, actual_price = pos.volume, pos.price_open
        
        # Validate position parameters (outside lock to allow close_position to acquire its own lock)
        mismatch_reason = self._validate_sl_tp_consistency(
            ticket, symbol_name, actual_sl, actual_tp, expected_sl, expected_tp, threshold
        )
        if mismatch_reason:
            self.position_closer.close_position(ticket)
            return False

        mismatch_reason = self._validate_volume_consistency(
            ticket, symbol_name, actual_volume, expected_volume
        )
        if mismatch_reason:
            self.position_closer.close_position(ticket)
            return False

        mismatch_reason = self._validate_price_consistency(
            ticket, symbol_name, actual_price, expected_price, point
        )
        if mismatch_reason:
            self.position_closer.close_position(ticket)
            return False

        logger.info(f"Position parameters verified for ticket {ticket} ({symbol_name}).")
        return True

    def _get_active_position(self, ticket: int):
        """Helper to get a single active position by its unique ticket ID."""
        positions = self.mt5.positions_get(ticket=ticket)
        return positions[0] if positions else None

    def _validate_sl_tp_consistency(
        self, ticket: int, symbol_name: str, actual_sl: float, actual_tp: float,
        expected_sl: float, expected_tp: float, threshold: float
    ) -> Optional[str]:
        """Validate that SL/TP values match expected values within threshold.
        
        Returns:
            "sl_tp" if mismatch found, None otherwise.
        """
        sl_match = abs(actual_sl - expected_sl) < threshold if expected_sl > 0 else (actual_sl == 0)
        tp_match = abs(actual_tp - expected_tp) < threshold if expected_tp > 0 else (actual_tp == 0)
        
        if not sl_match or not tp_match:
            logger.warning(f"SL/TP MISMATCH for ticket {ticket} ({symbol_name})! "
                           f"Requested: {expected_sl}/{expected_tp}, Actual: {actual_sl}/{actual_tp}")
            return "sl_tp"
        return None

    def _validate_volume_consistency(
        self, ticket: int, symbol_name: str, actual_volume: float, expected_volume: float
    ) -> Optional[str]:
        """Validate that volume matches expected value exactly (with small epsilon).
        
        Returns:
            "volume" if mismatch found, None otherwise.
        """
        if expected_volume > 0 and abs(actual_volume - expected_volume) > 0.00001:
            logger.warning(f"VOLUME MISMATCH for ticket {ticket} ({symbol_name})! "
                           f"Requested: {expected_volume}, Actual: {actual_volume}")
            return "volume"
        return None

    def _validate_price_consistency(
        self, ticket: int, symbol_name: str, actual_price: float, expected_price: float, point: float
    ) -> Optional[str]:
        """Validate that open price matches expected value within allowed slippage.
        
        Returns:
            "price" if mismatch found, None otherwise.
        """
        if expected_price > 0:
            max_allowed_slip = point * MT5_DEVIATION
            actual_slippage = abs(actual_price - expected_price)
            # Use small epsilon for float comparison safety
            if actual_slippage > (max_allowed_slip + 1e-9):
                logger.warning(
                    f"PRICE MISMATCH (SLIPPAGE) for ticket {ticket} ({symbol_name})! "
                    f"Requested: {expected_price}, Actual: {actual_price}, "
                    f"Slippage: {actual_slippage:.5f}, Limit: {max_allowed_slip:.5f}"
                )
                return "price"
        return None

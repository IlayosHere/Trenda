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
        
        # Capture position data atomically inside lock and perform validation
        # We keep the lock during validation to prevent position state from changing
        # between data capture and validation decision
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
            
            # Normalize expected values to match what was sent to MT5
            # This prevents false mismatches due to rounding differences
            symbol_digits = getattr(sym_info, 'digits', 5) if sym_info else 5
            volume_step_val = getattr(sym_info, 'volume_step', None) if sym_info else None
            # Handle MagicMock or None by ensuring we have a numeric value
            if volume_step_val is None or not isinstance(volume_step_val, (int, float)):
                volume_step = 0.01
            else:
                volume_step = volume_step_val if volume_step_val > 0 else 0.01
            
            expected_sl_rounded = round(expected_sl, symbol_digits) if expected_sl > 0 else 0.0
            expected_tp_rounded = round(expected_tp, symbol_digits) if expected_tp > 0 else 0.0
            expected_volume_rounded = self._round_to_volume_step(expected_volume, volume_step)
            
            # Perform validation while still holding lock to ensure consistency
            # This prevents race conditions where position changes between capture and validation
            mismatch_reason = (
                self._validate_sl_tp_consistency(
                    ticket, symbol_name, actual_sl, actual_tp, expected_sl_rounded, expected_tp_rounded, threshold
                ) or
                self._validate_volume_consistency(
                    ticket, symbol_name, actual_volume, expected_volume_rounded, volume_step
                ) or
                self._validate_price_consistency(
                    ticket, symbol_name, actual_price, expected_price, point
                )
            )
        
        # Now outside lock: close position if mismatch was detected
        # This allows close_position to acquire its own lock without deadlock
        if mismatch_reason:
            self.position_closer.close_position(ticket)
            return False

        logger.info(f"Position parameters verified for ticket {ticket} ({symbol_name}).")
        return True

    def _get_active_position(self, ticket: int):
        """Helper to get a single active position by its unique ticket ID.
        
        Returns:
            Position object if found, None otherwise.
        """
        try:
            positions = self.mt5.positions_get(ticket=ticket)
            if not positions:  # None or empty list
                return None
            return positions[0]
        except (IndexError, TypeError, AttributeError) as e:
            logger.error(f"Error getting position {ticket}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting position {ticket}: {e}")
            return None
    
    @staticmethod
    def _round_to_volume_step(volume: float, volume_step: float) -> float:
        """Round volume to the nearest volume_step.
        
        This matches the normalization done in order placement.
        """
        if volume <= 0 or volume_step <= 0:
            return volume
        return round(volume / volume_step) * volume_step

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
        self, ticket: int, symbol_name: str, actual_volume: float, expected_volume: float, volume_step: float
    ) -> Optional[str]:
        """Validate that volume matches expected value.
        
        Uses volume_step-based epsilon since both volumes are normalized to volume_step.
        
        Returns:
            "volume" if mismatch found, None otherwise.
        """
        if expected_volume <= 0:
            return None  # Skip validation if no expected volume
        
        # Use volume_step / 10 as epsilon (more appropriate than fixed 0.00001)
        epsilon = max(volume_step / 10, 1e-6)
        if abs(actual_volume - expected_volume) > epsilon:
            logger.warning(f"VOLUME MISMATCH for ticket {ticket} ({symbol_name})! "
                           f"Requested: {expected_volume}, Actual: {actual_volume}, Step: {volume_step}")
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

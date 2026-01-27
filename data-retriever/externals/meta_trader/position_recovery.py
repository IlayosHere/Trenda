"""Position recovery system for crash scenarios.

On system startup:
1. Fetch all active MT5 positions (filtered by magic number)
2. Check which ones exist in the database
3. Create recovery records for missing positions

This ensures positions opened before a crash are properly tracked.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from logger import get_logger
from configuration.broker_config import MT5_MAGIC_NUMBER
from database.executor import DBExecutor
from database.validation import DBValidator

logger = get_logger(__name__)

# Matching tolerance: 5 pips price difference, 24 hour time window
PRICE_TOLERANCE_PIPS = 5
TIME_WINDOW_HOURS = 24

# Check if signal exists in DB
CHECK_SIGNAL_EXISTS = """
    SELECT id
    FROM trenda.entry_signal
    WHERE symbol = %s
      AND entry_price IS NOT NULL
      AND ABS(entry_price - %s) < %s
      AND signal_time >= %s
    LIMIT 1
"""

# Create recovery record (minimal required fields)
INSERT_RECOVERY_SIGNAL = """
    INSERT INTO trenda.entry_signal (
        symbol, signal_time, direction,
        aoi_timeframe, aoi_low, aoi_high,
        entry_price, atr_1h,
        htf_score, obstacle_score, total_score,
        sl_model, sl_distance_atr, tp_distance_atr, rr_multiple,
        is_break_candle_last,
        htf_range_position_daily, htf_range_position_weekly,
        distance_to_next_htf_obstacle_atr, conflicted_tf
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""


class PositionRecovery:
    """Handles recovery of positions after system crash."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5
    
    def recover_positions(self) -> Dict[str, Any]:
        """Recover all active MT5 positions and sync with database.
        
        Returns:
            Dict with recovery statistics: {total_positions, matched, recovered, errors, details}
        """
        if not self.connection.initialize():
            logger.error("Cannot recover positions: MT5 initialization failed")
            return self._empty_stats(['MT5 init failed'])
        
        stats = self._empty_stats()
        
        try:
            # Get all positions with our magic number
            all_positions = self.mt5.positions_get()
            if all_positions is None:
                logger.info("No positions found in MT5")
                return stats
            
            bot_positions = [p for p in all_positions if p.magic == MT5_MAGIC_NUMBER]
            stats['total_positions'] = len(bot_positions)
            
            if not bot_positions:
                logger.info("No active positions found")
                return stats
            
            logger.info(f"🔍 Found {len(bot_positions)} active position(s) to check")
            
            # Check each position
            for pos in bot_positions:
                self._check_and_recover_position(pos, stats)
            
            # Log summary
            self._log_summary(stats)
            return stats
            
        except Exception as e:
            logger.error(f"Position recovery failed: {e}")
            stats['errors'] += 1
            stats['details'].append(f"Recovery failed: {str(e)}")
            return stats
    
    def _empty_stats(self, initial_details=None) -> Dict[str, Any]:
        """Create empty stats dict."""
        return {
            'total_positions': 0,
            'matched': 0,
            'recovered': 0,
            'errors': 0,
            'details': initial_details or []
        }
    
    def _check_and_recover_position(self, position: Any, stats: Dict[str, Any]) -> None:
        """Check if position exists in DB, create recovery record if missing."""
        try:
            result = self._process_position(position)
            
            if result['matched']:
                stats['matched'] += 1
                stats['details'].append(f"✅ Ticket {position.ticket} ({position.symbol}): Already in DB")
            elif result['recovered']:
                stats['recovered'] += 1
                stats['details'].append(f"🆕 Ticket {position.ticket} ({position.symbol}): Created recovery record")
            elif result['error']:
                stats['errors'] += 1
                stats['details'].append(f"❌ Ticket {position.ticket} ({position.symbol}): {result['error']}")
        except Exception as e:
            stats['errors'] += 1
            logger.error(f"Error processing position {position.ticket}: {e}")
            stats['details'].append(f"❌ Ticket {position.ticket}: {str(e)}")
    
    def _log_summary(self, stats: Dict[str, Any]) -> None:
        """Log recovery summary."""
        if stats['recovered'] > 0:
            logger.warning(f"⚠️ Recovered {stats['recovered']} position(s) missing from DB")
        elif stats['matched'] == stats['total_positions'] and stats['total_positions'] > 0:
            logger.info(f"✅ All {stats['matched']} position(s) are tracked in DB")
    
    def _process_position(self, position: Any) -> Dict[str, Any]:
        """Check if position exists in DB, create recovery record if missing.
        
        Returns:
            Dict with 'matched', 'recovered', 'error' keys
        """
        # Extract position data
        symbol = position.symbol
        entry_price = position.price_open
        direction = "BULLISH" if position.type == self.mt5.POSITION_TYPE_BUY else "BEARISH"
        
        # Validate symbol
        normalized_symbol = DBValidator.validate_symbol(symbol)
        if not normalized_symbol:
            return {'matched': False, 'recovered': False, 'error': f'Invalid symbol: {symbol}'}
        
        # Get symbol info for price tolerance calculation
        sym_info = self.mt5.symbol_info(symbol)
        if not sym_info or sym_info.point <= 0:
            return {'matched': False, 'recovered': False, 'error': f'Cannot get symbol info for {symbol}'}
        
        # Calculate price tolerance (5 pips)
        price_tolerance = self._calculate_price_tolerance(sym_info)
        time_window_start = datetime.now(timezone.utc) - timedelta(hours=TIME_WINDOW_HOURS)
        
        # Check if already in DB
        if self._check_signal_exists(normalized_symbol, entry_price, price_tolerance, time_window_start):
            return {'matched': True, 'recovered': False, 'error': None}
        
        # Not found - create recovery record
        recovery_id = self._create_recovery_record(position, normalized_symbol, entry_price, direction, sym_info)
        if recovery_id:
            logger.warning(f"🆕 Recovered: Ticket {position.ticket} ({symbol}) @ {entry_price:.5f} | ID: {recovery_id}")
            return {'matched': False, 'recovered': True, 'error': None}
        
        return {'matched': False, 'recovered': False, 'error': 'Failed to create recovery record'}
    
    def _calculate_price_tolerance(self, sym_info: Any) -> float:
        """Calculate price tolerance in price units (5 pips)."""
        digits = sym_info.digits
        point = sym_info.point
        pip_size = point * 10 if digits in (3, 5) else point
        return pip_size * PRICE_TOLERANCE_PIPS
    
    def _check_signal_exists(self, symbol: str, entry_price: float, tolerance: float, time_start: datetime) -> bool:
        """Check if a signal exists in DB matching this position."""
        def _check(cursor):
            cursor.execute(
                CHECK_SIGNAL_EXISTS,
                (symbol, entry_price, tolerance, time_start)
            )
            return cursor.fetchone() is not None
        
        result = DBExecutor.execute_transaction(_check, context="check_signal_exists")
        return result if result is not None else False
    
    def _create_recovery_record(self, position: Any, symbol: str, entry_price: float, 
                                direction: str, sym_info: Any) -> Optional[int]:
        """Create a recovery record for a position missing from DB.
        
        Uses minimal required data - marks as "RECOVERY" for identification.
        """
        # Get position open time (fallback to 1 hour ago if unavailable)
        signal_time = self._get_position_time(position)
        
        # Estimate ATR (0.5% of entry price - conservative)
        atr_1h = entry_price * 0.005
        
        # Calculate SL/TP distances in ATR units
        sl_distance_atr = self._calculate_sl_distance_atr(position.sl, entry_price, atr_1h)
        tp_distance_atr = self._calculate_tp_distance_atr(position.tp, entry_price, atr_1h)
        
        # Estimate AOI bounds (entry price ± 1% or ± 2 ATR)
        aoi_low = min(entry_price * 0.99, entry_price - (atr_1h * 2))
        aoi_high = max(entry_price * 1.01, entry_price + (atr_1h * 2))
        
        # Insert recovery record
        def _persist(cursor):
            cursor.execute(
                INSERT_RECOVERY_SIGNAL,
                (
                    symbol, signal_time, direction,
                    "1H", aoi_low, aoi_high,  # AOI data
                    entry_price, atr_1h,  # Entry data
                    None, None, None,  # Scores (unknown)
                    "RECOVERY", sl_distance_atr, tp_distance_atr, None,  # SL/TP
                    False,  # is_break_candle_last
                    None, None, None, None  # HTF context (unknown)
                ),
            )
            return cursor.fetchone()[0]
        
        return DBExecutor.execute_transaction(_persist, context="create_recovery_record")
    
    def _get_position_time(self, position: Any) -> datetime:
        """Get position open time, fallback to 1 hour ago if unavailable."""
        try:
            if hasattr(position, 'time') and position.time > 0:
                return datetime.fromtimestamp(position.time, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            pass
        
        # Fallback: 1 hour ago (conservative estimate)
        fallback_time = datetime.now(timezone.utc) - timedelta(hours=1)
        logger.warning(f"Position {position.ticket} has no time, using fallback: {fallback_time}")
        return fallback_time
    
    def _calculate_sl_distance_atr(self, sl_price: float, entry_price: float, atr_1h: float) -> Optional[float]:
        """Calculate SL distance in ATR units."""
        if sl_price <= 0 or atr_1h <= 0:
            return None
        return abs(entry_price - sl_price) / atr_1h
    
    def _calculate_tp_distance_atr(self, tp_price: float, entry_price: float, atr_1h: float) -> Optional[float]:
        """Calculate TP distance in ATR units."""
        if tp_price <= 0 or atr_1h <= 0:
            return None
        return abs(tp_price - entry_price) / atr_1h

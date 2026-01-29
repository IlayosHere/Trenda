from typing import NamedTuple
from datetime import datetime, timedelta
from logger import get_logger
from configuration.broker_config import (
    MT5_MAGIC_NUMBER, 
    MT5_MAX_ACTIVE_TRADES, 
    MT5_MIN_TRADE_INTERVAL_MINUTES,
    MT5_HISTORY_LOOKBACK_DAYS
)
from .safeguards import _trading_lock

logger = get_logger(__name__)

class TradeBlockStatus(NamedTuple):
    """Result of a trade constraint check."""
    is_blocked: bool
    reason: str

class MT5Constraints:
    """Checks and validates trading constraints."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5

    def can_execute_trade(self, symbol: str) -> TradeBlockStatus:
        """Checks if a new trade can be opened for the given symbol.
        
        Returns:
            TradeBlockStatus: is_blocked=True if trade is not allowed, with a reason string.
        """
        # 0. Check if trading is locked (before any MT5 calls)
        is_allowed, lock_reason = _trading_lock.is_trading_allowed()
        if not is_allowed:
            return TradeBlockStatus(True, f"🔒 TRADING LOCKED: {lock_reason}")
        
        if not self.connection.initialize():
            return TradeBlockStatus(True, "MT5 initialization failed")
            
        with self.connection.lock:
            # 1. Ensure symbol is visible
            symbol_info = self.mt5.symbol_info(symbol)
            if symbol_info is None:
                return TradeBlockStatus(True, f"Symbol {symbol} not found")
            
            if not symbol_info.visible:
                if not self.mt5.symbol_select(symbol, True):
                    return TradeBlockStatus(True, f"Failed to select symbol {symbol}")

            # 2. Get server time from current tick
            tick = self.mt5.symbol_info_tick(symbol)
            if not tick:
                return TradeBlockStatus(True, f"Failed to get tick for {symbol} to check server time")
            current_server_time = tick.time

            # 3. Fetch all active positions once
            all_positions = self.mt5.positions_get()
            if all_positions is None:
                err = self.mt5.last_error()
                if err[0] != 1: # 1 = Success / No positions
                     logger.error(f"Failed to get positions: {err}")
                     return TradeBlockStatus(True, "Error fetching active positions")
                all_positions = []
            
            # Layered Filtering:
            # Stage A: Filter for this bot's trades across all symbols
            algo_positions = [p for p in all_positions if p.magic == MT5_MAGIC_NUMBER]
            
            # 4. Check global trade limit
            status = self._check_global_limit(algo_positions)
            if status.is_blocked:
                return status

            # Stage B: Filter further for this specific symbol's bot trades
            symbol_algo_positions = [p for p in algo_positions if p.symbol == symbol]

            # 5. Check per-symbol limit (cooldown and active)
            status = self._check_symbol_limit(symbol, current_server_time, symbol_algo_positions)
            if status.is_blocked:
                return status
                
        return TradeBlockStatus(False, "")

    def _check_global_limit(self, algo_positions: list) -> TradeBlockStatus:
        """Checks if the maximum allowed global trades for this bot has been reached."""
        if len(algo_positions) >= MT5_MAX_ACTIVE_TRADES:
            return TradeBlockStatus(True, f"Global limit reached: {len(algo_positions)} active trades")
        
        return TradeBlockStatus(False, "")

    def _check_symbol_limit(self, symbol: str, current_server_time: float, symbol_algo_positions: list) -> TradeBlockStatus:
        """Checks if enough time has passed since the last trade for this symbol."""
        # Convert minutes from config to seconds for precision
        min_gap_seconds = MT5_MIN_TRADE_INTERVAL_MINUTES * 60 

        # 1. Check active positions for this symbol
        if symbol_algo_positions:
            most_recent_start_time = max(p.time for p in symbol_algo_positions)
            seconds_since_last_pos = current_server_time - most_recent_start_time
            if seconds_since_last_pos < min_gap_seconds:
                hours_ago = seconds_since_last_pos / 3600
                return TradeBlockStatus(True, f"Recent active position for {symbol} found ({hours_ago:.1f}h ago server time).")

        # 2. Check historical deals (based on configured lookback)
        from_date = datetime.fromtimestamp(current_server_time) - timedelta(days=MT5_HISTORY_LOOKBACK_DAYS)
        to_date = datetime.fromtimestamp(current_server_time + 60)
        history = self.mt5.history_deals_get(from_date, to_date, group=f"*{symbol}*")
            
        if history:
            bot_deals = [d for d in history if d.magic == MT5_MAGIC_NUMBER and d.entry == self.mt5.DEAL_ENTRY_IN]
            if bot_deals:
                last_deal_time = max(d.time for d in bot_deals)
                seconds_since_last_deal = current_server_time - last_deal_time
                if seconds_since_last_deal < min_gap_seconds:
                    hours_ago = seconds_since_last_deal / 3600
                    return TradeBlockStatus(True, f"Recent historical trade for {symbol} found ({hours_ago:.1f}h ago server time).")

        return TradeBlockStatus(False, "")

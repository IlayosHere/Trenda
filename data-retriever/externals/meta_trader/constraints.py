from datetime import datetime, timedelta
from logger import get_logger
from configuration.broker_config import MT5_MAGIC_NUMBER, MT5_MAX_ACTIVE_TRADES, MT5_MIN_TRADE_INTERVAL_HOURS

logger = get_logger(__name__)

class MT5Constraints:
    """Checks and validates trading constraints."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5

    def is_trade_open(self, symbol: str) -> tuple[bool, str]:
        """Checks if a new trade can be opened for the given symbol."""
        if not self.connection.initialize():
            return True, "MT5 initialization failed"
            
        with self.connection.lock:
            # 1. Get server time from current tick
            tick = self.mt5.symbol_info_tick(symbol)
            if not tick:
                return True, f"Failed to get tick for {symbol} to check server time"
            
            current_server_time = tick.time

            # 2. Total active trades limit check
            all_positions = self.mt5.positions_get()
            if all_positions is None:
                err = self.mt5.last_error()
                if err[0] != 1: # 1 = Success / No positions
                     logger.error(f"Failed to get positions: {err}")
                     return True, "Error fetching active positions"
                all_positions = []
                
            bot_positions = [p for p in all_positions if p.magic == MT5_MAGIC_NUMBER]
            if len(bot_positions) >= MT5_MAX_ACTIVE_TRADES:
                return True, f"Global limit reached: {len(bot_positions)} active trades"

            # 3. Per-symbol time limit check
            symbol_positions = [p for p in bot_positions if p.symbol == symbol]
            if symbol_positions:
                most_recent_start_time = max(p.time for p in symbol_positions)
                hours_since_last_pos = (current_server_time - most_recent_start_time) / 3600
                if hours_since_last_pos < MT5_MIN_TRADE_INTERVAL_HOURS:
                    return True, f"Recent active position for {symbol} found ({hours_since_last_pos:.1f}h ago server time)."

            # 3b. Check historical deals
            from_date = datetime.fromtimestamp(current_server_time) - timedelta(days=1)
            to_date = datetime.fromtimestamp(current_server_time + 60)
            history = self.mt5.history_deals_get(from_date, to_date, group=f"*{symbol}*")
                
            if history:
                bot_deals = [d for d in history if d.magic == MT5_MAGIC_NUMBER and d.entry == self.mt5.DEAL_ENTRY_IN]
                if bot_deals:
                    last_deal_time = max(d.time for d in bot_deals)
                    hours_since_last_deal = (current_server_time - last_deal_time) / 3600
                    if hours_since_last_deal < MT5_MIN_TRADE_INTERVAL_HOURS:
                        return True, f"Recent historical trade for {symbol} found ({hours_since_last_deal:.1f}h ago server time)."
                
        return False, ""

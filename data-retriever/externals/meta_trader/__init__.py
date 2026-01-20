"""MetaTrader 5 Integration Package."""
from .connection import MT5Connection
from .trading import MT5Trader
from .constraints import MT5Constraints

# Singleton instances for global access (similar to old the mt5_handler module)
_connection = MT5Connection()
_trader = MT5Trader(_connection)
_constraints = MT5Constraints(_connection)

# Re-export MetaTrader5 constants if available
mt5 = _connection.mt5
mt5_lock = _connection.lock

# Public API functions (matches old mt5_handler.py interface)
initialize_mt5 = _connection.initialize
shutdown_mt5 = _connection.shutdown
place_order = _trader.place_order
close_position = _trader.close_position
verify_position_consistency = _trader.verify_position_consistency
can_execute_trade = _constraints.can_execute_trade

__all__ = [
    "mt5",
    "mt5_lock",
    "initialize_mt5",
    "shutdown_mt5",
    "place_order",
    "close_position",
    "verify_position_consistency",
    "can_execute_trade",
]

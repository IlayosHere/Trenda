try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from configuration import MT5_MAGIC_NUMBER, MT5_DEVIATION, MT5_DEFAULT_LOT_SIZE
from logger import get_logger

logger = get_logger(__name__)

# Flag to track if MT5 has been initialized in this session
_mt5_initialized = False

def initialize_mt5():
    """Initializes and checks the MT5 connection only once per session."""
    global _mt5_initialized
    
    if mt5 is None:
        logger.warning("MetaTrader5 package not found. Skipping initialization.")
        return False
        
    if _mt5_initialized:
        return True

    if not mt5.initialize():
        logger.error(f"MT5 initialization failed. Error: {mt5.last_error()}")
        return False
    
    logger.info("✅ MT5 initialized successfully.")
    _mt5_initialized = True
    return True

def shutdown_mt5():
    """Shuts down the MT5 connection and resets state."""
    global _mt5_initialized
    if mt5 is not None:
        logger.info("Shutting down MT5 connection...")
        mt5.shutdown()
    _mt5_initialized = False

def place_market_order(symbol: str, order_type: int, volume: float = MT5_DEFAULT_LOT_SIZE, sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, comment: str = ""):
    """Places a market order in MT5."""
    if not initialize_mt5():
        return None

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error(f"Symbol {symbol} not found.")
        return None

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            logger.error(f"Failed to select symbol {symbol}.")
            return None

    # Determine execution price
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"Failed to get tick info for {symbol}. Error: {mt5.last_error()}")
        return None

    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,      # Type of trade: direct deal (market order)
        "symbol": symbol,                     # Trading instrument (e.g., "EURUSD")
        "volume": volume,                     # Order size in lots (e.g., 0.1)
        "type": order_type,                   # Order direction: mt5.ORDER_TYPE_BUY or mt5.ORDER_TYPE_SELL
        "price": price,                       # Current market price for execution
        "sl": sl,                             # Stop Loss price level
        "tp": tp,                             # Take Profit price level
        "deviation": deviation,               # Max allowed slippage in points
        "magic": MT5_MAGIC_NUMBER,            # Unique ID to identify trades from this bot
        "comment": comment,                   # Personal note for the trade (e.g., "Trenda Strategy")
        "type_time": mt5.ORDER_TIME_GTC,      # Order duration: Good 'Til Cancelled
        "type_filling": mt5.ORDER_FILLING_IOC,# Filling policy: Immediate Or Cancel
    }

    result = mt5.order_send(request)
    if result is None:
        logger.error(f"Order send failed for {symbol}. Result is None.")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed for {symbol}. Retcode: {result.retcode}, Error: {mt5.last_error()}")
        return result

    logger.info(f"🚀 Market order placed successfully for {symbol}. Ticket: {result.order}")
    return result

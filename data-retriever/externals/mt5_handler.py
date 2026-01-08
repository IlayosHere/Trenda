try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from configuration import MT5_MAGIC_NUMBER, MT5_DEVIATION, MT5_DEFAULT_LOT_SIZE, MT5_EXPIRATION_MINUTES
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

def place_order(symbol: str, order_type: int, price: float = 0.0, volume: float = MT5_DEFAULT_LOT_SIZE, sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, magic: int = MT5_MAGIC_NUMBER, comment: str = "", expiration_minutes: int = MT5_EXPIRATION_MINUTES):
    """
    Unified function to place any type of order in MT5 with automatic 10-minute expiration.
    
    Args:
        symbol: The trading instrument (e.g., "EURUSD").
        order_type: Direction (mt5.ORDER_TYPE_BUY/SELL) or Pending (mt5.ORDER_TYPE_BUY_LIMIT/STOP, etc.).
        price: The price for pending orders. If 0.0, it uses current market price for direct deals.
        volume: Order size in lots.
        sl: Stop loss price.
        tp: Take profit price.
        deviation: Max allowed slippage (points).
        magic: Unique identifier for the EA/bot (default from config).
        comment: Personal note.
        expiration_minutes: Minutes after which the order is canceled if not filled (default 10).
    """
    if not initialize_mt5():
        return None

    # 1. Ensure symbol is visible and select it
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logger.error(f"Symbol {symbol} not found.")
        return None
    
    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            logger.error(f"Failed to select symbol {symbol}.")
            return None

    # 2. Get current price
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"Failed to get tick info for {symbol}. Error: {mt5.last_error()}")
        return None

    if price == 0.0:
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    # 3. Normalize prices (Round to symbol's digits)
    price = round(price, symbol_info.digits)
    sl = round(sl, symbol_info.digits) if sl > 0 else 0.0
    tp = round(tp, symbol_info.digits) if tp > 0 else 0.0

    # 4. Calculate expiration timestamp (Server time + minutes)
    expiration_time = int(tick.time + (expiration_minutes * 60))

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_SPECIFIED,
        "expiration": expiration_time,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    
    if result is None:
        logger.error(f"Order send failed for {symbol}. Result is None.")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Order failed for {symbol}. Action: {mt5.TRADE_ACTION_DEAL}, Retcode: {result.retcode}, Error: {mt5.last_error()}")
        return result

    # 5. Success Logging
    logger.info(f"✅ Success: Order placed - sym:{symbol}, vol:{volume}, type:{order_type}, price:{price}, ticket:{result.order}")
    
    return result

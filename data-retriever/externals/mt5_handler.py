import MetaTrader5 as mt5
from configuration import MT5_MAGIC_NUMBER

_mt5_initialized = False

def initialize_mt5():
    """Initializes and checks the MT5 connection only once."""
    global _mt5_initialized
    if _mt5_initialized:
        return True

    if not mt5.initialize():
        print(f"MT5 initialization failed. Error: {mt5.last_error()}")
        return False
    
    print("MT5 initialized successfully.")
    _mt5_initialized = True
    return True


def shutdown_mt5():
    global _mt5_initialized
    print("Shutting down MT5 connection...")
    mt5.shutdown()
    _mt5_initialized = False


def place_market_order(symbol: str, order_type: int, volume: float, sl: float = 0.0, tp: float = 0.0, deviation: int = 20, comment: str = ""):
    """Places a market order in MT5."""
    if not initialize_mt5():
        return None

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"Symbol {symbol} not found.")
        return None

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            print(f"Failed to select symbol {symbol}.")
            return None

    # Determine execution price
    tick = mt5.symbol_info_tick(symbol) #function used to get the latest price data
    if tick is None:
        print(f"Failed to get tick info for {symbol}. Error: {mt5.last_error()}")
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
        "deviation": deviation,                      # Max allowed slippage in points
        "magic": MT5_MAGIC_NUMBER,            # Unique ID to identify trades from this bot
        "comment": comment,                   # Personal note for the trade (e.g., "Trenda Strategy")
        "type_time": mt5.ORDER_TIME_GTC,      # Order duration: Good 'Til Cancelled
        "type_filling": mt5.ORDER_FILLING_IOC,# Filling policy: Immediate Or Cancel
    }

    result = mt5.order_send(request)
    if result is None:
        print(f"Order send failed for {symbol}. Result is None.")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order failed for {symbol}. Retcode: {result.retcode}, Error: {mt5.last_error()}")
        return result

    print(f"Market order placed successfully for {symbol}. Ticket: {result.order}")
    return result

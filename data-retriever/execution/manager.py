import MetaTrader5 as mt5
import utils.display as display
from models import TrendDirection

class ExecutionManager:
    """Manages the execution flow from signal to MT5 trade."""

    DEFAULT_LOT_SIZE = 0.01

    @classmethod
    def process_signal(
        cls,
        signal_id: int,
        symbol: str,
        direction: TrendDirection,
        aoi_low: float,
        aoi_high: float,
        trade_quality: float,
    ):
        """Validates and executes a trade based on a detected signal."""
        display.print_status(f"  [EXECUTION] Processing signal {signal_id} for {symbol}...")

        from externals.mt5_handler import place_market_order

        # 1. Basic Validation
        if trade_quality < 0.5:  # Example threshold
            display.print_status(f"  [EXECUTION] Signal {signal_id} rejected: quality {trade_quality} too low.")
            return False

        # 2. Prevent Duplicates (Simple check: is there already a trade open for this symbol?)
        if cls._is_trade_open(symbol):
            display.print_status(f"  [EXECUTION] Signal {signal_id} skipped: trade already open for {symbol}.")
            return False

        # 3. Determine Order Type
        order_type = mt5.ORDER_TYPE_BUY if direction == TrendDirection.BULLISH else mt5.ORDER_TYPE_SELL

        # 4. Calculate SL/TP (Simple logic: AOI bounds)
        # For Buy: SL at AOI low, TP at AOI high + (AOI high - AOI low) * 2 (as an example)
        # For Sell: SL at AOI high, TP at AOI low - (AOI high - AOI low) * 2
        aoi_height = aoi_high - aoi_low
        if order_type == mt5.ORDER_TYPE_BUY:
            sl = aoi_low
            tp = aoi_high + (aoi_height * 2)
        else:
            sl = aoi_high
            tp = aoi_low - (aoi_height * 2)

        # 5. Place Trade
        comment = f"SignalID:{signal_id}"
        result = place_market_order(
            symbol=symbol,
            order_type=order_type,
            volume=cls.DEFAULT_LOT_SIZE,
            sl=sl,
            tp=tp,
            comment=comment
        )

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            display.print_status(f"  [EXECUTION] ✅ Trade executed for {symbol} (Ticket: {result.order})")
            return True
        else:
            display.print_error(f"  [EXECUTION] ❌ Trade failed for {symbol}.")
            return False

    @staticmethod
    def _is_trade_open(symbol: str) -> bool:
        """Checks if there are any open positions for the given symbol."""
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return False
        return len(positions) > 0

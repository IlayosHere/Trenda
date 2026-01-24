from typing import Optional, Any, Tuple
from logger import get_logger
from configuration.broker_config import (
    MT5_MAGIC_NUMBER, MT5_DEVIATION, MT5_EXPIRATION_SECONDS
)
from configuration.trading_config import MT5_ORDER_COMMENT

logger = get_logger(__name__)


class OrderPlacer:
    """Handles order placement operations for MT5."""
    
    def __init__(self, connection):
        self.connection = connection
        self.mt5 = connection.mt5

    def place_order(self, symbol: str, order_type: int, volume: float, price: float = 0.0, 
                    sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, 
                    magic: int = MT5_MAGIC_NUMBER, comment: str = MT5_ORDER_COMMENT,
                    expiration_seconds: int = MT5_EXPIRATION_SECONDS) -> Optional[Any]:
        """Place an order in MT5 with a strict expiration window.
        
        Returns:
            mt5.OrderSendResult or None: The result of the order placement.
        """
        # Input validation
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            logger.error(f"Invalid symbol: {symbol}. Must be a non-empty string.")
            return None
        
        if volume <= 0:
            logger.error(f"Invalid volume: {volume}. Must be > 0")
            return None
        
        # Validate order_type is a valid MT5 constant
        valid_order_types = (self.mt5.ORDER_TYPE_BUY, self.mt5.ORDER_TYPE_SELL)
        if order_type not in valid_order_types:
            logger.error(f"Invalid order_type: {order_type}. Must be ORDER_TYPE_BUY ({self.mt5.ORDER_TYPE_BUY}) or ORDER_TYPE_SELL ({self.mt5.ORDER_TYPE_SELL})")
            return None
        
        if expiration_seconds < 0:
            logger.error(f"Invalid expiration_seconds: {expiration_seconds}. Must be >= 0")
            return None
        
        if deviation < 0:
            logger.error(f"Invalid deviation: {deviation}. Must be >= 0")
            return None
        
        if not self.connection.initialize():
            return None

        with self.connection.lock:
            symbol_info = self._ensure_symbol_available(symbol)
            if symbol_info is None:
                return None

            if not self._validate_trade_mode(symbol, symbol_info):
                return None

            if not self._validate_price(symbol, price):
                return None

            # Normalize volume to symbol's volume_step (like we do for prices)
            volume = self._normalize_volume(symbol, symbol_info, volume)
            if volume is None:
                return None

            price, sl, tp = self._normalize_prices(symbol, symbol_info, price, sl, tp)
            if price is None:
                return None

            if not self._validate_sl_tp_distances(symbol, symbol_info, price, sl, tp):
                return None

            expiration_time = self._calculate_expiration_time(symbol, expiration_seconds)
            if expiration_time is None:
                return None

            request = self._build_order_request(
                symbol, order_type, volume, price, sl, tp, 
                deviation, magic, comment, expiration_time
            )

            result = self.mt5.order_send(request)
        
        return self._process_order_result(symbol, order_type, volume, price, result)

    def _ensure_symbol_available(self, symbol: str) -> Optional[Any]:
        """Ensure symbol is visible and select it if needed.
        
        Returns:
            Symbol info if available, None otherwise.
        """
        symbol_info = self.mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.error(f"Symbol {symbol} not found.")
            return None
        
        if not symbol_info.visible:
            if not self.mt5.symbol_select(symbol, True):
                logger.error(f"Failed to select symbol {symbol}.")
                return None
        
        return symbol_info

    def _validate_trade_mode(self, symbol: str, symbol_info: Any) -> bool:
        """Validate that trading is allowed for the symbol.
        
        Returns:
            True if trading is allowed, False otherwise.
        """
        if symbol_info.trade_mode == self.mt5.SYMBOL_TRADE_MODE_DISABLED:
            logger.error(f"Order failed: Trading is DISABLED for {symbol}.")
            return False
        if symbol_info.trade_mode == self.mt5.SYMBOL_TRADE_MODE_CLOSEONLY:
            logger.error(f"Order failed: Symbol {symbol} is in CLOSE-ONLY mode.")
            return False
        return True

    def _validate_price(self, symbol: str, price: float) -> bool:
        """Validate that price is not zero.
        
        Returns:
            True if price is valid, False otherwise.
        """
        if price == 0.0:
            logger.error(f"Order failed for {symbol}: price is 0.0. A valid price must be provided.")
            return False
        return True

    def _normalize_volume(self, symbol: str, symbol_info: Any, volume: float) -> Optional[float]:
        """Normalize volume by rounding to symbol's volume_step and clamping to min/max.
        
        MT5 requires volume to be a multiple of volume_step and within [volume_min, volume_max].
        This ensures the volume we send matches what MT5 will actually accept.
        
        Returns:
            Normalized volume or None if invalid.
        """
        volume_step = symbol_info.volume_step
        volume_min = symbol_info.volume_min
        volume_max = symbol_info.volume_max
        
        if volume_step <= 0:
            logger.error(f"Order failed for {symbol}: Invalid volume_step ({volume_step}).")
            return None
        
        # Round to nearest volume_step
        normalized_volume = round(volume / volume_step) * volume_step
        
        # Clamp to min/max
        if normalized_volume < volume_min:
            logger.error(f"Order failed for {symbol}: Volume {normalized_volume} is below minimum {volume_min}.")
            return None
        
        if normalized_volume > volume_max:
            logger.error(f"Order failed for {symbol}: Volume {normalized_volume} exceeds maximum {volume_max}.")
            return None
        
        return normalized_volume

    def _normalize_prices(self, symbol: str, symbol_info: Any, price: float, 
                         sl: float, tp: float) -> Tuple[Optional[float], float, float]:
        """Normalize prices by rounding to symbol's digits and validate SL/TP are non-negative.
        
        Returns:
            Tuple of (normalized_price, normalized_sl, normalized_tp) or (None, 0.0, 0.0) if invalid.
        """
        price = round(price, symbol_info.digits)
        
        if sl < 0 or tp < 0:
            logger.error(f"Order failed for {symbol}: SL/TP cannot be negative (sl={sl}, tp={tp}).")
            return None, 0.0, 0.0

        sl = round(sl, symbol_info.digits) if sl > 0 else 0.0
        tp = round(tp, symbol_info.digits) if tp > 0 else 0.0
        
        return price, sl, tp

    def _validate_sl_tp_distances(self, symbol: str, symbol_info: Any, 
                                  price: float, sl: float, tp: float) -> bool:
        """Validate that SL/TP distances meet minimum requirements (Stops Level & Freeze Level).
        
        Returns:
            True if distances are valid, False otherwise.
        """
        if sl == 0 and tp == 0:
            return True

        min_dist_points = max(symbol_info.trade_stops_level, symbol_info.trade_freeze_level)
        min_dist_price = round(min_dist_points * symbol_info.point, symbol_info.digits)
        
        if sl > 0:
            dist_sl = round(abs(price - sl), symbol_info.digits)
            if dist_sl < min_dist_price:
                logger.error(f"Order failed for {symbol}: SL too close to price. "
                             f"Dist: {dist_sl:.5f}, Min: {min_dist_price:.5f} ({min_dist_points} pts)")
                return False
        
        if tp > 0:
            dist_tp = round(abs(tp - price), symbol_info.digits)
            if dist_tp < min_dist_price:
                logger.error(f"Order failed for {symbol}: TP too close to price. "
                             f"Dist: {dist_tp:.5f}, Min: {min_dist_price:.5f} ({min_dist_points} pts)")
                return False
        
        return True

    def _calculate_expiration_time(self, symbol: str, expiration_seconds: int) -> Optional[int]:
        """Calculate expiration timestamp based on current tick time.
        
        Returns:
            Expiration timestamp or None if tick info cannot be retrieved.
        """
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"Failed to get tick info for {symbol}. Error: {self.mt5.last_error()}")
            return None
        return int(tick.time + expiration_seconds)

    def _build_order_request(self, symbol: str, order_type: int, volume: float, 
                            price: float, sl: float, tp: float, deviation: int,
                            magic: int, comment: str, expiration_time: int) -> dict:
        """Build the order request dictionary.
        
        Returns:
            Dictionary containing order request parameters.
        """
        return {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": deviation,
            "magic": magic,
            "comment": comment,
            "type_time": self.mt5.ORDER_TIME_SPECIFIED,
            "expiration": expiration_time,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }

    def _process_order_result(self, symbol: str, order_type: int, volume: float, 
                              price: float, result: Optional[Any]) -> Optional[Any]:
        """Process the order send result and log appropriately.
        
        Returns:
            Order result if successful, None or result object if failed.
        """
        if result is None:
            logger.error(f"Order send failed for {symbol}. Result is None.")
            return None

        # Safe attribute access: check if retcode exists before accessing
        if not hasattr(result, 'retcode'):
            logger.error(f"Order result for {symbol} missing 'retcode' attribute. Result type: {type(result)}")
            return None

        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            self._log_order_error(symbol, result)
            return result

        # Safe access to result.order - use getattr with None default
        ticket = getattr(result, 'order', None)
        if ticket is None:
            logger.warning(f"Order succeeded for {symbol} but no ticket returned. Result: {result}")
            # Still return result even without ticket for caller to handle
            return result
        
        logger.info(f"Success: Order placed - sym:{symbol}, vol:{volume}, type:{order_type}, price:{price}, ticket:{ticket}")
        return result

    def _log_order_error(self, symbol: str, result: Any):
        """Helper to log detailed MT5 order errors."""
        error_messages = {
            10004: "Requote - price changed",
            10006: "Request rejected",
            10007: "Request canceled by trader",
            10010: "Only part of request completed",
            10013: "Invalid request",
            10014: "Invalid volume",
            10015: "Invalid price",
            10016: "Invalid stops (SL/TP)",
            10017: "Trade disabled",
            10018: "Market closed",
            10019: "Insufficient funds",
            10020: "Prices changed",
            10021: "No quotes",
            10022: "Invalid order expiration",
            10024: "Too frequent requests",
            10026: "AutoTrading disabled by server",
            10027: "AutoTrading disabled in terminal (enable Algo Trading button)",
            10030: "Invalid SL/TP for this symbol",
        }
        # Safe access to retcode
        retcode = getattr(result, 'retcode', None)
        if retcode is None:
            logger.error(f"Order failed for {symbol}. Result missing 'retcode' attribute. Result: {result}")
            return
        
        desc = error_messages.get(retcode, "Unknown error")
        mt5_error = self.mt5.last_error() if hasattr(self.mt5, 'last_error') else "N/A"
        logger.error(f"Order failed for {symbol}. Retcode: {retcode} ({desc}), MT5 Error: {mt5_error}")

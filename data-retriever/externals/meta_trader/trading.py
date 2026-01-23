from typing import Optional, Any
from configuration.broker_config import (
    MT5_MAGIC_NUMBER, MT5_DEVIATION, MT5_EXPIRATION_SECONDS
)
from configuration.trading_config import MT5_ORDER_COMMENT
from .order_placement import OrderPlacer
from .position_closing import PositionCloser
from .position_verification import PositionVerifier


class MT5Trader:
    """Handles trading operations like placing orders and closing positions."""
    
    def __init__(self, connection):
        self.connection = connection
        self._order_placer = OrderPlacer(connection)
        self._position_closer = PositionCloser(connection)
        self._position_verifier = PositionVerifier(connection, self._position_closer)

    def place_order(self, symbol: str, order_type: int, volume: float, price: float = 0.0, 
                    sl: float = 0.0, tp: float = 0.0, deviation: int = MT5_DEVIATION, 
                    magic: int = MT5_MAGIC_NUMBER, comment: str = MT5_ORDER_COMMENT,
                    expiration_seconds: int = MT5_EXPIRATION_SECONDS) -> Optional[Any]:
        """Place an order in MT5 with a strict expiration window.
        
        Returns:
            mt5.OrderSendResult or None: The result of the order placement.
        """
        return self._order_placer.place_order(
            symbol, order_type, volume, price, sl, tp, 
            deviation, magic, comment, expiration_seconds
        )

    def close_position(self, ticket: int) -> bool:
        """Closes an active position by its ticket ID with retry logic and verification."""
        return self._position_closer.close_position(ticket)

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
        return self._position_verifier.verify_position_consistency(
            ticket, expected_sl, expected_tp, expected_volume, expected_price
        )

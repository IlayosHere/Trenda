"""Live execution data for signal firing.

Fetches real-time price from MT5 and calculates execution parameters:
- Live entry price (ask for buy, bid for sell)
- SL/TP prices based on live price
- Lot size based on risk percentage and account balance
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from configuration.broker_config import BROKER_MT5, BROKER_PROVIDER
from models import TrendDirection
from entry.gates.config import SL_BUFFER_ATR, RR_MULTIPLE

if BROKER_PROVIDER == BROKER_MT5:
    import MetaTrader5 as mt5
else:
    mt5 = None  # type: ignore


# Default risk percentage per trade
DEFAULT_RISK_PERCENT: float = 2.0  # 2% of account balance


@dataclass
class ExecutionData:
    """Live execution parameters for trade entry."""
    symbol: str
    direction: TrendDirection
    lot_size: float
    entry_price: float  # Live price (ask for buy, bid for sell)
    sl_price: float     # Stop loss price
    tp_price: float     # Take profit price
    sl_distance_pips: float
    tp_distance_pips: float
    atr_1h: float
    sl_distance_atr: float
    tp_distance_atr: float


def get_live_price(symbol: str, direction: TrendDirection) -> Optional[float]:
    """Get live bid/ask price from MT5.
    
    Args:
        symbol: Trading symbol
        direction: Trade direction (BULLISH = buy at ask, BEARISH = sell at bid)
        
    Returns:
        Live price or None if unavailable
    """
    if mt5 is None:
        return None
    
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    
    if direction == TrendDirection.BULLISH:
        return tick.ask  # Buy at ask
    else:
        return tick.bid  # Sell at bid


def get_symbol_info(symbol: str) -> Optional[dict]:
    """Get symbol info for pip value and lot calculations."""
    if mt5 is None:
        return None
    
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    
    return {
        "point": info.point,
        "digits": info.digits,
        "trade_contract_size": info.trade_contract_size,
        "volume_min": info.volume_min,
        "volume_max": info.volume_max,
        "volume_step": info.volume_step,
    }


def get_account_balance() -> Optional[float]:
    """Get current account balance from MT5."""
    if mt5 is None:
        return None
    
    account_info = mt5.account_info()
    if account_info is None:
        return None
    
    return account_info.balance


def calculate_pip_value(symbol: str, lot_size: float = 1.0) -> Optional[float]:
    """Calculate pip value for a given symbol and lot size."""
    info = get_symbol_info(symbol)
    if info is None:
        return None
    
    # Standard forex: 1 pip = 0.0001 (or 0.01 for JPY pairs)
    point = info["point"]
    digits = info["digits"]
    
    # Pip is typically 10 points for 5-digit brokers
    if digits == 3 or digits == 5:
        pip_size = point * 10
    else:
        pip_size = point
    
    # For standard forex, pip value = lot_size * pip_size * contract_size
    contract_size = info["trade_contract_size"]
    
    return lot_size * pip_size * contract_size


def calculate_lot_size(
    symbol: str,
    sl_distance_price: float,
    risk_percent: float = DEFAULT_RISK_PERCENT,
) -> Optional[float]:
    """Calculate lot size based on risk percentage and SL distance.
    
    Args:
        symbol: Trading symbol
        sl_distance_price: SL distance in price units
        risk_percent: Percentage of account balance to risk (default 1%)
        
    Returns:
        Lot size rounded to symbol's volume step
    """
    balance = get_account_balance()
    if balance is None or balance <= 0:
        return None
    
    info = get_symbol_info(symbol)
    if info is None:
        return None
    
    # Risk amount in account currency
    risk_amount = balance * (risk_percent / 100)
    
    # Get pip value for 1 lot
    pip_value_per_lot = calculate_pip_value(symbol, 1.0)
    if pip_value_per_lot is None or pip_value_per_lot <= 0:
        return None
    
    # Convert SL distance to pips
    point = info["point"]
    digits = info["digits"]
    pip_size = point * 10 if digits in (3, 5) else point
    sl_distance_pips = sl_distance_price / pip_size
    
    if sl_distance_pips <= 0:
        return None
    
    # Lot size = risk_amount / (sl_pips * pip_value_per_lot)
    lot_size = risk_amount / (sl_distance_pips * pip_value_per_lot)
    
    # Round to volume step
    volume_step = info["volume_step"]
    volume_min = info["volume_min"]
    volume_max = info["volume_max"]
    
    lot_size = round(lot_size / volume_step) * volume_step
    lot_size = max(volume_min, min(volume_max, lot_size))
    
    return round(lot_size, 2)


def compute_execution_data(
    symbol: str,
    direction: TrendDirection,
    aoi_low: float,
    aoi_high: float,
    atr_1h: float,
    risk_percent: float = DEFAULT_RISK_PERCENT,
) -> Optional[ExecutionData]:
    """Compute live execution data for a signal.
    
    Uses real-time price for all calculations. Call this as close
    to actual trade execution as possible.
    
    Args:
        symbol: Trading symbol
        direction: Trade direction
        aoi_low: AOI lower bound
        aoi_high: AOI upper bound  
        atr_1h: 1H ATR for SL distance calculation
        risk_percent: Risk percentage (default 1%)
        
    Returns:
        ExecutionData with all execution parameters or None if unavailable
    """
    # Get live price
    entry_price = get_live_price(symbol, direction)
    if entry_price is None:
        return None
    
    # Calculate SL distance using SL_AOI_FAR_PLUS_0_25 model
    if direction == TrendDirection.BULLISH:
        # Far edge is aoi_low (below entry)
        far_edge_distance = entry_price - aoi_low
    else:
        # Far edge is aoi_high (above entry)
        far_edge_distance = aoi_high - entry_price
    
    # SL in ATR units
    sl_distance_atr = (far_edge_distance / atr_1h) + SL_BUFFER_ATR
    tp_distance_atr = sl_distance_atr * RR_MULTIPLE
    
    # Convert to price distance
    sl_distance_price = sl_distance_atr * atr_1h
    tp_distance_price = tp_distance_atr * atr_1h
    
    # Calculate SL/TP prices
    if direction == TrendDirection.BULLISH:
        sl_price = entry_price - sl_distance_price
        tp_price = entry_price + tp_distance_price
    else:
        sl_price = entry_price + sl_distance_price
        tp_price = entry_price - tp_distance_price
    
    # Calculate lot size
    lot_size = calculate_lot_size(symbol, sl_distance_price, risk_percent)
    if lot_size is None:
        lot_size = 0.01  # Fallback to minimum
    
    # Get symbol info for pip conversion
    info = get_symbol_info(symbol)
    if info:
        point = info["point"]
        digits = info["digits"]
        pip_size = point * 10 if digits in (3, 5) else point
        sl_distance_pips = sl_distance_price / pip_size
        tp_distance_pips = tp_distance_price / pip_size
    else:
        sl_distance_pips = 0.0
        tp_distance_pips = 0.0
    
    return ExecutionData(
        symbol=symbol,
        direction=direction,
        lot_size=lot_size,
        entry_price=round(entry_price, 5),
        sl_price=round(sl_price, 5),
        tp_price=round(tp_price, 5),
        sl_distance_pips=round(sl_distance_pips, 1),
        tp_distance_pips=round(tp_distance_pips, 1),
        atr_1h=atr_1h,
        sl_distance_atr=round(sl_distance_atr, 3),
        tp_distance_atr=round(tp_distance_atr, 3),
    )

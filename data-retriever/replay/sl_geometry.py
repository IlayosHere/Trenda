"""SL geometry calculation for exit simulation.

Computes AOI and signal candle geometry at entry time.
This is independent of scoring and SL choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from models import TrendDirection

if TYPE_CHECKING:
    pass


@dataclass
class SLGeometryData:
    """SL-relevant geometry at entry time."""
    
    direction: str
    
    # AOI-based geometry
    aoi_far_edge_atr: float         # Distance from entry to far edge of AOI
    aoi_near_edge_atr: float        # Distance from entry to near edge of AOI
    aoi_height_atr: float           # Vertical height of AOI
    aoi_age_bars: Optional[int]     # Bars since AOI creation
    
    # Signal candle geometry
    signal_candle_opposite_extreme_atr: float  # Distance to opposite extreme
    signal_candle_range_atr: float             # Total candle range
    signal_candle_body_atr: float              # Candle body size
    lookahead_drift_atr: float                 # Price drift during lookahead period


class SLGeometryCalculator:
    """Computes AOI and signal candle geometry at entry."""
    
    def __init__(
        self,
        entry_price: float,
        atr_at_entry: float,
        direction: TrendDirection,
        aoi_low: float,
        aoi_high: float,
        signal_candle: dict,         # {open, high, low, close}
        aoi_creation_time: Optional[datetime] = None,
        signal_time: Optional[datetime] = None,
    ):
        self._entry_price = entry_price
        self._atr = atr_at_entry
        self._direction = direction
        self._is_long = direction == TrendDirection.BULLISH
        self._aoi_low = aoi_low
        self._aoi_high = aoi_high
        self._signal_candle = signal_candle
        self._aoi_creation_time = aoi_creation_time
        self._signal_time = signal_time
    
    def compute(self) -> Optional[SLGeometryData]:
        """Compute SL geometry.
        
        Returns:
            SLGeometryData with all geometry values, or None if invalid
        """
        if self._atr <= 0:
            return None
        
        # AOI geometry
        aoi_far_edge, aoi_near_edge = self._compute_aoi_edges()
        aoi_height = (self._aoi_high - self._aoi_low) / self._atr
        
        # AOI age (approximate - hours between creation and signal)
        aoi_age_bars = None
        if self._aoi_creation_time and self._signal_time:
            delta = self._signal_time - self._aoi_creation_time
            aoi_age_bars = int(delta.total_seconds() / 3600)
        
        # Signal candle geometry
        candle_geometry = self._compute_signal_candle_geometry()
        
        return SLGeometryData(
            direction=self._direction.value,
            aoi_far_edge_atr=aoi_far_edge,
            aoi_near_edge_atr=aoi_near_edge,
            aoi_height_atr=aoi_height,
            aoi_age_bars=aoi_age_bars,
            signal_candle_opposite_extreme_atr=candle_geometry["opposite_extreme"],
            signal_candle_range_atr=candle_geometry["range"],
            signal_candle_body_atr=candle_geometry["body"],
            lookahead_drift_atr=candle_geometry["drift"],
        )
    
    def _compute_aoi_edges(self) -> tuple[float, float]:
        """Compute far and near edge distances from entry to AOI.
        
        Far edge: the edge opposite to trade direction (where SL goes)
        Near edge: the edge in trade direction
        
        Returns:
            (far_edge_atr, near_edge_atr)
        """
        if self._is_long:
            # Bullish: far edge is aoi_low (below entry), near edge is aoi_high
            far_edge = abs(self._entry_price - self._aoi_low) / self._atr
            near_edge = abs(self._entry_price - self._aoi_high) / self._atr
        else:
            # Bearish: far edge is aoi_high (above entry), near edge is aoi_low
            far_edge = abs(self._aoi_high - self._entry_price) / self._atr
            near_edge = abs(self._aoi_low - self._entry_price) / self._atr
        
        return far_edge, near_edge
    
    def _compute_signal_candle_geometry(self) -> dict:
        """Compute signal candle geometry metrics.
        
        Returns:
            dict with opposite_extreme, range, body in ATR units
        """
        c = self._signal_candle
        high = c["high"]
        low = c["low"]
        open_price = c["open"]
        close = c["close"]
        
        candle_range = (high - low) / self._atr
        body = abs(close - open_price) / self._atr
        
        if self._is_long:
            # Bullish: opposite extreme is the low
            opposite_extreme = (self._entry_price - low) / self._atr
            # Drift: (Close - Entry) / ATR
            drift = (close - self._entry_price) / self._atr
        else:
            # Bearish: opposite extreme is the high
            opposite_extreme = (high - self._entry_price) / self._atr
            # Drift: (Entry - Close) / ATR
            drift = (self._entry_price - close) / self._atr
        
        return {
            "opposite_extreme": opposite_extreme,
            "range": candle_range,
            "body": body,
            "drift": drift,
        }


def persist_sl_geometry(signal_id: int, data: SLGeometryData) -> None:
    """Persist SL geometry to database."""
    from database.executor import DBExecutor
    from .replay_queries import INSERT_ENTRY_SL_GEOMETRY
    
    DBExecutor.execute_non_query(
        INSERT_ENTRY_SL_GEOMETRY,
        (
            signal_id,
            data.direction,
            data.aoi_far_edge_atr,
            data.aoi_near_edge_atr,
            data.aoi_height_atr,
            data.aoi_age_bars,
            data.signal_candle_opposite_extreme_atr,
            data.signal_candle_range_atr,
            data.signal_candle_body_atr,
            data.lookahead_drift_atr,
        ),
        context="persist_sl_geometry",
    )

"""Pre-entry context computation for replay.

Computes observable metrics from candles strictly before the entry candle.
All window sizes are controlled by constants in config.py.

Design principles:
- Use full candle range (high/low) for AOI interaction
- Use body only (open/close) for directional movement
- Normalize everything by ATR
- All metrics are direction-aware
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

from models import TrendDirection

from .config import (
    PRE_ENTRY_LOOKBACK_BARS,
    PRE_ENTRY_IMPULSE_BARS,
    PRE_ENTRY_LARGE_BAR_WINDOW,
    PRE_ENTRY_LONG_ATR_WINDOW,
)

if TYPE_CHECKING:
    from .candle_store import CandleStore


@dataclass
class PreEntryContextData:
    """Pre-entry observable facts computed at replay time."""
    
    # Metadata
    lookback_bars: int
    impulse_bars: int
    
    # Volatility & range
    pre_atr: Optional[float] = None
    pre_atr_ratio: Optional[float] = None
    pre_range_atr: Optional[float] = None
    pre_range_to_atr_ratio: Optional[float] = None
    
    # Directional pressure
    pre_net_move_atr: Optional[float] = None
    pre_total_move_atr: Optional[float] = None
    pre_efficiency: Optional[float] = None
    pre_counter_bar_ratio: Optional[float] = None
    
    # AOI interaction
    pre_aoi_touch_count: Optional[int] = None
    pre_bars_in_aoi: Optional[int] = None
    pre_last_touch_distance_atr: Optional[float] = None
    
    # Impulse / energy
    pre_impulse_net_atr: Optional[float] = None
    pre_impulse_efficiency: Optional[float] = None
    pre_large_bar_ratio: Optional[float] = None
    
    # Microstructure
    pre_overlap_ratio: Optional[float] = None
    pre_wick_ratio: Optional[float] = None


def _to_python_float(value) -> Optional[float]:
    """Convert numpy types to native Python float for DB compatibility."""
    if value is None:
        return None
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    return float(value) if value is not None else None


def _to_python_int(value) -> Optional[int]:
    """Convert numpy types to native Python int for DB compatibility."""
    if value is None:
        return None
    if isinstance(value, (np.floating, np.integer)):
        return int(value)
    return int(value) if value is not None else None


class PreEntryContextCalculator:
    """Computes pre-entry context metrics from candle data.
    
    All computations use candles strictly before the entry candle.
    """
    
    def __init__(
        self,
        candle_store: "CandleStore",
        signal_time: datetime,
        direction: TrendDirection,
        aoi_low: float,
        aoi_high: float,
    ):
        self._store = candle_store
        self._signal_time = signal_time
        self._direction = direction
        self._aoi_low = aoi_low
        self._aoi_high = aoi_high
        self._is_long = direction == TrendDirection.BULLISH
    
    def compute(self) -> Optional[PreEntryContextData]:
        """Compute all pre-entry context metrics.
        
        Returns:
            PreEntryContextData with all computed metrics, or None if insufficient data.
        """
        # Get candles strictly before signal time
        candles_1h = self._store.get_1h_candles().get_candles_up_to(self._signal_time)
        if candles_1h is None or candles_1h.empty:
            return None
        
        # Exclude the entry candle itself (use candles before entry)
        # The signal_time is the time of the entry candle, so we need candles before it
        candles_before = candles_1h[candles_1h["time"] < self._signal_time].copy()
        if len(candles_before) < PRE_ENTRY_LOOKBACK_BARS:
            return None
        
        # Get main lookback window (last N candles before entry)
        main_window = candles_before.tail(PRE_ENTRY_LOOKBACK_BARS)
        
        # Get long window for ATR ratio (need more history)
        long_window = candles_before.tail(PRE_ENTRY_LONG_ATR_WINDOW)
        
        # Get impulse window (shorter, most recent)
        impulse_window = candles_before.tail(PRE_ENTRY_IMPULSE_BARS)
        
        # Get large bar window
        large_bar_window = candles_before.tail(PRE_ENTRY_LARGE_BAR_WINDOW)
        
        # Compute pre_atr first (needed for normalization)
        pre_atr = self._compute_pre_atr(main_window)
        if pre_atr is None or pre_atr <= 0:
            return None
        
        # Compute all metrics
        volatility = self._compute_volatility_metrics(main_window, long_window, pre_atr)
        directional = self._compute_directional_metrics(main_window, pre_atr)
        aoi_metrics = self._compute_aoi_metrics(main_window, candles_before, pre_atr)
        impulse = self._compute_impulse_metrics(impulse_window, pre_atr)
        large_bar = self._compute_large_bar_ratio(large_bar_window, main_window)
        microstructure = self._compute_microstructure_metrics(main_window)
        
        return PreEntryContextData(
            lookback_bars=PRE_ENTRY_LOOKBACK_BARS,
            impulse_bars=PRE_ENTRY_IMPULSE_BARS,
            # Volatility
            pre_atr=_to_python_float(pre_atr),
            pre_atr_ratio=_to_python_float(volatility.get("pre_atr_ratio")),
            pre_range_atr=_to_python_float(volatility.get("pre_range_atr")),
            pre_range_to_atr_ratio=_to_python_float(volatility.get("pre_range_to_atr_ratio")),
            # Directional
            pre_net_move_atr=_to_python_float(directional.get("pre_net_move_atr")),
            pre_total_move_atr=_to_python_float(directional.get("pre_total_move_atr")),
            pre_efficiency=_to_python_float(directional.get("pre_efficiency")),
            pre_counter_bar_ratio=_to_python_float(directional.get("pre_counter_bar_ratio")),
            # AOI
            pre_aoi_touch_count=_to_python_int(aoi_metrics.get("pre_aoi_touch_count")),
            pre_bars_in_aoi=_to_python_int(aoi_metrics.get("pre_bars_in_aoi")),
            pre_last_touch_distance_atr=_to_python_float(aoi_metrics.get("pre_last_touch_distance_atr")),
            # Impulse
            pre_impulse_net_atr=_to_python_float(impulse.get("pre_impulse_net_atr")),
            pre_impulse_efficiency=_to_python_float(impulse.get("pre_impulse_efficiency")),
            pre_large_bar_ratio=_to_python_float(large_bar),
            # Microstructure
            pre_overlap_ratio=_to_python_float(microstructure.get("pre_overlap_ratio")),
            pre_wick_ratio=_to_python_float(microstructure.get("pre_wick_ratio")),
        )
    
    def _compute_pre_atr(self, candles: pd.DataFrame) -> Optional[float]:
        """Compute average ATR over the lookback window.
        
        Uses the ATR value from each candle (True Range) and takes arithmetic mean.
        """
        if len(candles) < 2:
            return None
        
        # Compute True Range for each candle
        highs = candles["high"].values
        lows = candles["low"].values
        closes = candles["close"].values
        
        # TR = max(high - low, |high - prev_close|, |low - prev_close|)
        prev_closes = np.roll(closes, 1)
        tr1 = highs - lows
        tr2 = np.abs(highs - prev_closes)
        tr3 = np.abs(lows - prev_closes)
        
        true_ranges = np.maximum(tr1, np.maximum(tr2, tr3))
        # Skip first element (no previous close)
        true_ranges = true_ranges[1:]
        
        if len(true_ranges) == 0:
            return None
        
        return float(np.mean(true_ranges))
    
    def _compute_volatility_metrics(
        self,
        main_window: pd.DataFrame,
        long_window: pd.DataFrame,
        pre_atr: float,
    ) -> dict:
        """Compute volatility and range metrics."""
        result = {}
        
        # pre_atr_ratio: pre_atr / median_atr_over_long_window
        if len(long_window) >= PRE_ENTRY_LONG_ATR_WINDOW // 2:
            long_atr = self._compute_pre_atr(long_window)
            if long_atr and long_atr > 0:
                # Use median of rolling ATR values for stability
                result["pre_atr_ratio"] = pre_atr / long_atr
        
        # pre_range_atr: (max(high) - min(low)) / pre_atr
        max_high = main_window["high"].max()
        min_low = main_window["low"].min()
        total_range = max_high - min_low
        result["pre_range_atr"] = total_range / pre_atr if pre_atr > 0 else None
        
        # pre_range_to_atr_ratio: pre_range_atr / lookback_bars
        if result.get("pre_range_atr") is not None:
            result["pre_range_to_atr_ratio"] = result["pre_range_atr"] / PRE_ENTRY_LOOKBACK_BARS
        
        return result
    
    def _compute_directional_metrics(
        self,
        candles: pd.DataFrame,
        pre_atr: float,
    ) -> dict:
        """Compute directional pressure and balance metrics.
        
        All metrics are direction-aware (sign adjusted for long vs short).
        """
        result = {}
        
        if len(candles) < 2:
            return result
        
        # Get first open and last close
        first_open = candles.iloc[0]["open"]
        last_close = candles.iloc[-1]["close"]
        
        # pre_net_move_atr: (last_close - first_open) / pre_atr
        # Direction-aware: positive = pressure aligned with trade direction
        raw_net_move = last_close - first_open
        if not self._is_long:
            raw_net_move = -raw_net_move  # Invert for short trades
        result["pre_net_move_atr"] = raw_net_move / pre_atr if pre_atr > 0 else None
        
        # pre_total_move_atr: SUM(ABS(close - open)) / pre_atr
        body_moves = np.abs(candles["close"].values - candles["open"].values)
        total_move = float(np.sum(body_moves))
        result["pre_total_move_atr"] = total_move / pre_atr if pre_atr > 0 else None
        
        # pre_efficiency: ABS(pre_net_move_atr) / pre_total_move_atr
        if result.get("pre_net_move_atr") is not None and result.get("pre_total_move_atr"):
            if result["pre_total_move_atr"] > 0:
                result["pre_efficiency"] = abs(result["pre_net_move_atr"]) / result["pre_total_move_atr"]
        
        # pre_counter_bar_ratio: COUNT(counter_direction_closes) / total_bars
        # Long: close < open (bearish candle = counter)
        # Short: close > open (bullish candle = counter)
        closes = candles["close"].values
        opens = candles["open"].values
        
        if self._is_long:
            counter_bars = np.sum(closes < opens)
        else:
            counter_bars = np.sum(closes > opens)
        
        result["pre_counter_bar_ratio"] = counter_bars / len(candles)
        
        return result
    
    def _compute_aoi_metrics(
        self,
        main_window: pd.DataFrame,
        all_candles: pd.DataFrame,
        pre_atr: float,
    ) -> dict:
        """Compute AOI interaction metrics.
        
        Uses full candle range (high/low) for interaction detection, not just body.
        """
        result = {}
        
        aoi_low = self._aoi_low
        aoi_high = self._aoi_high
        
        # Determine if each candle is inside AOI
        # candle_inside_aoi = high >= aoi_low AND low <= aoi_high
        highs = main_window["high"].values
        lows = main_window["low"].values
        
        inside_aoi = (highs >= aoi_low) & (lows <= aoi_high)
        
        # pre_bars_in_aoi: Total candles interacting with AOI
        result["pre_bars_in_aoi"] = int(np.sum(inside_aoi))
        
        # pre_aoi_touch_count: Number of distinct entry sequences into AOI
        # Count transitions: outside -> inside
        touch_count = 0
        was_inside = False
        for is_inside in inside_aoi:
            if is_inside and not was_inside:
                touch_count += 1
            was_inside = is_inside
        result["pre_aoi_touch_count"] = touch_count
        
        # pre_last_touch_distance_atr: Distance from AOI on last pre-entry candle
        # Use the very last candle before entry
        if len(main_window) > 0:
            last_candle = main_window.iloc[-1]
            last_close = last_candle["close"]
            
            # Distance = min(|close - aoi_low|, |close - aoi_high|)
            dist_to_low = abs(last_close - aoi_low)
            dist_to_high = abs(last_close - aoi_high)
            min_distance = min(dist_to_low, dist_to_high)
            
            result["pre_last_touch_distance_atr"] = min_distance / pre_atr if pre_atr > 0 else None
        
        return result
    
    def _compute_impulse_metrics(
        self,
        impulse_window: pd.DataFrame,
        pre_atr: float,
    ) -> dict:
        """Compute impulse/energy metrics over the short impulse window."""
        result = {}
        
        if len(impulse_window) < 2:
            return result
        
        # pre_impulse_net_atr: (last_close - first_open) / pre_atr
        first_open = impulse_window.iloc[0]["open"]
        last_close = impulse_window.iloc[-1]["close"]
        
        raw_impulse_net = last_close - first_open
        if not self._is_long:
            raw_impulse_net = -raw_impulse_net
        
        result["pre_impulse_net_atr"] = raw_impulse_net / pre_atr if pre_atr > 0 else None
        
        # pre_impulse_efficiency: ABS(net_impulse) / SUM(ABS(bar_moves))
        body_moves = np.abs(impulse_window["close"].values - impulse_window["open"].values)
        total_impulse_move = float(np.sum(body_moves))
        
        if total_impulse_move > 0 and result.get("pre_impulse_net_atr") is not None:
            # Raw efficiency (not normalized by ATR, just ratio)
            raw_efficiency = abs(raw_impulse_net) / total_impulse_move
            result["pre_impulse_efficiency"] = raw_efficiency
        
        return result
    
    def _compute_large_bar_ratio(
        self,
        large_bar_window: pd.DataFrame,
        main_window: pd.DataFrame,
    ) -> Optional[float]:
        """Compute ratio of bars with large bodies.
        
        Large = |close - open| > avg_body_size_over_main_window
        """
        if len(large_bar_window) == 0 or len(main_window) == 0:
            return None
        
        # Compute average body size over main lookback window
        main_bodies = np.abs(main_window["close"].values - main_window["open"].values)
        avg_body_size = float(np.mean(main_bodies))
        
        if avg_body_size <= 0:
            return None
        
        # Count large bars in the large_bar_window
        window_bodies = np.abs(large_bar_window["close"].values - large_bar_window["open"].values)
        large_bar_count = np.sum(window_bodies > avg_body_size)
        
        return large_bar_count / len(large_bar_window)
    
    def _compute_microstructure_metrics(self, candles: pd.DataFrame) -> dict:
        """Compute microstructure cleanliness metrics."""
        result = {}
        
        if len(candles) < 2:
            return result
        
        highs = candles["high"].values
        lows = candles["low"].values
        opens = candles["open"].values
        closes = candles["close"].values
        
        # pre_overlap_ratio: sum(overlapping_range) / total_range
        # overlapping_range = min(high_i, high_{i-1}) - max(low_i, low_{i-1})
        total_overlap = 0.0
        for i in range(1, len(candles)):
            overlap_high = min(highs[i], highs[i - 1])
            overlap_low = max(lows[i], lows[i - 1])
            overlap = max(0.0, overlap_high - overlap_low)
            total_overlap += overlap
        
        total_range = highs.max() - lows.min()
        if total_range > 0:
            result["pre_overlap_ratio"] = total_overlap / total_range
        
        # pre_wick_ratio: total_wick_size / total_range
        # wick = (high - max(open, close)) + (min(open, close) - low)
        upper_wicks = highs - np.maximum(opens, closes)
        lower_wicks = np.minimum(opens, closes) - lows
        total_wick = float(np.sum(upper_wicks) + np.sum(lower_wicks))
        
        if total_range > 0:
            result["pre_wick_ratio"] = total_wick / total_range
        
        return result

"""Stateful market state management for replay.

Maintains trend and AOI state per symbol, updating only when
higher timeframe candles close. Reuses production logic for
all calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Mapping

import numpy as np
import pandas as pd

from models import AOIZone, TrendDirection
from trend.structure import TrendAnalysisResult, analyze_snake_trend, get_swing_points
from trend.bias import get_overall_trend_from_values, calculate_trend_alignment_strength
from aoi.pipeline import generate_aoi_zones
from aoi.scoring import apply_directional_weighting_and_classify
from aoi.context import build_context, extract_swings
from aoi.aoi_configuration import AOI_CONFIGS
from aoi.analyzer import filter_noisy_points
from configuration import require_analysis_params

from .candle_store import CandleStore
from .timeframe_alignment import (
    TimeframeAligner,
    get_candles_for_analysis,
)
from .config import (
    ACTIVE_PROFILE,
    TREND_ALIGNMENT_TIMEFRAMES,
)


@dataclass
class SymbolState:
    """Current market state for a symbol at a point in time."""
    
    # Dict-based storage keyed by TF string
    trends: dict[str, Optional[TrendDirection]] = field(default_factory=dict)
    trend_results: dict[str, Optional[TrendAnalysisResult]] = field(default_factory=dict)
    aois: dict[str, List[AOIZone]] = field(default_factory=dict)
    break_times: dict[str, Optional[datetime]] = field(default_factory=dict)
    last_updates: dict[str, Optional[datetime]] = field(default_factory=dict)
    
    # Backward-compatible accessors for trend_low / trend_mid / trend_high
    @property
    def trend_low(self) -> Optional[TrendDirection]:
        return self.trends.get(ACTIVE_PROFILE.trend_tf_low)
    
    @property
    def trend_mid(self) -> Optional[TrendDirection]:
        return self.trends.get(ACTIVE_PROFILE.trend_tf_mid)
    
    @property
    def trend_high(self) -> Optional[TrendDirection]:
        return self.trends.get(ACTIVE_PROFILE.trend_tf_high)
    
    def get_trend_snapshot(self) -> Mapping[str, Optional[TrendDirection]]:
        """Get trend values as a mapping for production functions."""
        p = ACTIVE_PROFILE
        return {
            p.trend_tf_low:  self.trends.get(p.trend_tf_low),
            p.trend_tf_mid:  self.trends.get(p.trend_tf_mid),
            p.trend_tf_high: self.trends.get(p.trend_tf_high),
        }
    
    def get_overall_trend(self) -> Optional[TrendDirection]:
        """Determine overall trend using production logic."""
        return get_overall_trend_from_values(
            self.get_trend_snapshot(),
            TREND_ALIGNMENT_TIMEFRAMES,
        )
    
    def get_tradable_aois(self) -> List[AOIZone]:
        """Get all tradable AOIs from all AOI timeframes."""
        all_aois: List[AOIZone] = []
        for tf in (ACTIVE_PROFILE.aoi_tf_low, ACTIVE_PROFILE.aoi_tf_high):
            all_aois.extend(self.aois.get(tf, []))
        return [aoi for aoi in all_aois if aoi.classification == "tradable"]
    
    def get_trend_alignment_strength(self, direction: TrendDirection) -> int:
        """Count how many timeframes align with the given direction."""
        return calculate_trend_alignment_strength(
            self.get_trend_snapshot(),
            direction,
        )


class MarketStateManager:
    """Manages market state for a single symbol during replay.
    
    Updates trend and AOI states only when higher timeframes close,
    ensuring all state reflects only information available at each
    point in the replay.
    """
    
    def __init__(
        self,
        symbol: str,
        candle_store: CandleStore,
        aligner: TimeframeAligner,
    ):
        self._symbol = symbol
        self._store = candle_store
        self._aligner = aligner
        self._state = SymbolState()
        self._profile = ACTIVE_PROFILE
        
        # Which TFs get AOI computation
        self._aoi_tfs = {self._profile.aoi_tf_low, self._profile.aoi_tf_high}
    
    @property
    def state(self) -> SymbolState:
        """Get current market state."""
        return self._state
    
    def update_state(self, current_time: datetime) -> None:
        """Update market state based on new timeframe closes."""
        close_flags = self._aligner.detect_new_closes(current_time)
        
        for tf in self._profile.trend_alignment_tfs:
            if close_flags.is_new(tf):
                self._update_tf_state(tf, current_time)
    
    def _update_tf_state(self, tf: str, as_of_time: datetime) -> None:
        """Recompute trend (and possibly AOIs) for a given timeframe."""
        # --- Trend ---
        trend_lookback = self._profile.lookback_for_trend(tf)
        trend_candles = get_candles_for_analysis(
            self._store, tf, as_of_time, trend_lookback
        )
        
        if trend_candles is not None and not trend_candles.empty:
            result = self._compute_trend(trend_candles, tf)
            self._state.trend_results[tf] = result
            self._state.trends[tf] = result.trend if result else None
            self._state.break_times[tf] = self._resolve_break_time(
                trend_candles, result
            )
        
        # --- AOIs (only for AOI timeframes) ---
        if tf in self._aoi_tfs:
            aoi_lookback = self._profile.lookback_for_aoi(tf)
            aoi_candles = get_candles_for_analysis(
                self._store, tf, as_of_time, aoi_lookback
            )
            if aoi_candles is not None and not aoi_candles.empty:
                self._state.aois[tf] = self._compute_aois(
                    tf, aoi_candles, self._state.get_overall_trend()
                )
        
        self._state.last_updates[tf] = as_of_time
    
    def _compute_trend(self, candles: pd.DataFrame, tf: str) -> Optional[TrendAnalysisResult]:
        """Compute trend from candles using production logic."""
        if candles is None or candles.empty or "close" not in candles.columns:
            return None
        
        prices = candles["close"].values
        if len(prices) < 2:
            return None
        
        # Get analysis params for this timeframe
        try:
            params = require_analysis_params(tf)
            distance = params.distance
            prominence = params.prominence
        except KeyError:
            distance = 1
            prominence = 0.0004
        
        swings = get_swing_points(prices, distance, prominence)
        return analyze_snake_trend(swings)
    
    def _resolve_break_time(
        self, candles: pd.DataFrame, result: TrendAnalysisResult
    ) -> Optional[datetime]:
        """Find the exact time of the structural break."""
        if not result or not result.broken_swing or "close" not in candles.columns:
            return None
            
        broken_price = result.broken_swing.price
        # Break happens after broken_swing.index
        # We need to find the first candle AFTER broken_swing.index where Close crosses broken_price.
        
        start_idx = result.broken_swing.index + 1
        if start_idx >= len(candles):
            return None
            
        try:
            # Slicing creates a copy/view. We iterate row by row or vectorized.
            # We need the Time of the break candle.
            
            # Identify direction based on trend (if Bullish, break was up)
            # Actually result.trend tells us the *current* trend.
            # If broken_swing was a High, we broke UP (Bullish).
            # If broken_swing was a Low, we broke DOWN (Bearish).
            
            from trend.structure import SWING_HIGH, SWING_LOW
            
            # But TrendAnalysisResult doesn't store broken_swing.kind directly?
            # It stores SwingPoint, which has .kind.
            
            target_time = None
            is_break_up = result.broken_swing.kind == SWING_HIGH
            
            # Scan
            subset = candles.iloc[start_idx:]
            
            if is_break_up:
                # Find first close > price
                mask = subset["close"] > broken_price
            else:
                # Find first close < price
                mask = subset["close"] < broken_price
                
            # Get first True
            # mask is a Series of booleans.
            if mask.any():
                # idxmax() on boolean returns first True index
                first_true_idx = mask.idxmax()
                # Use the index to get the time.
                # If dataframe index is integer (default for reset_index), or if it is Time?
                # The 'candles' from `get_candles_for_analysis` usually comes from `store.get_Xh_candles().get_candles_up_to`.
                # CandleStore usually returns DF with 'formatted' time or just time column.
                # Let's assume 'time' column exists or index is time.
                # `market_state.py` usually deals with `candles` having properties.
                # Let's check `candles["time"]`.
                
                # Careful: idxmax() returns the *Label* of the index.
                # If candles index is RangeIndex, it works as position.
                # If candles index is Time, it returns Time.
                
                if "time" in candles.columns:
                    target_time = candles.loc[first_true_idx, "time"]
                else: 
                     # Fallback if Time is index
                     target_time = first_true_idx
                     
                return target_time
                
        except Exception:
            pass
            
        return None

    def _compute_aois(
        self,
        timeframe: str,
        candles: pd.DataFrame,
        trend_direction: Optional[TrendDirection],
    ) -> List[AOIZone]:
        """Compute AOIs from candles using production logic."""
        settings = AOI_CONFIGS.get(timeframe)
        if settings is None:
            return []
        
        if candles is None or candles.empty or "close" not in candles.columns:
            return []
        
        prices = np.asarray(candles["close"].values)
        last_bar_idx = len(prices) - 1
        current_price = float(prices[-1])
        
        # Build AOI context
        from utils.indicators import calculate_atr
        from utils.forex import get_pip_size, price_to_pips
        
        atr = calculate_atr(candles, length=14)
        pip_size = get_pip_size(self._symbol)
        atr_pips = price_to_pips(atr, pip_size) if atr > 0 else None
        
        context = build_context(settings, self._symbol, atr_pips)
        
        # Extract swings and generate zones
        swings = extract_swings(prices, context)
        important_swings = filter_noisy_points(swings)
        zones = generate_aoi_zones(important_swings, last_bar_idx, context)
        
        # Apply scoring and classification
        if trend_direction:
            zones_scored = apply_directional_weighting_and_classify(
                zones, current_price, trend_direction, context
            )
        else:
            zones_scored = zones
        
        # Return top zones
        max_zones = settings.max_zones_per_symbol
        top_zones = sorted(
            zones_scored, key=lambda z: z.score or 0.0, reverse=True
        )[:max_zones]
        
        # Add timeframe to each zone
        for zone in top_zones:
            zone.timeframe = timeframe
        
        return top_zones
    
    def reset(self) -> None:
        """Reset state for a new replay run."""
        self._state = SymbolState()
        self._aligner.reset()

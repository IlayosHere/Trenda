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
from constants import SwingPoint
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
    NewCloseFlags,
    get_candles_for_analysis,
)
from .config import (
    TIMEFRAME_4H,
    TIMEFRAME_1D,
    TIMEFRAME_1W,
    LOOKBACK_4H,
    LOOKBACK_1D,
    LOOKBACK_1W,
    LOOKBACK_AOI_4H,
    LOOKBACK_AOI_1D,
    TREND_ALIGNMENT_TIMEFRAMES,
)


@dataclass
class SymbolState:
    """Current market state for a symbol at a point in time."""
    
    # Trend states per timeframe
    trend_4h: Optional[TrendDirection] = None
    trend_1d: Optional[TrendDirection] = None
    trend_1w: Optional[TrendDirection] = None
    
    # Trend analysis results (for structural levels)
    trend_result_4h: Optional[TrendAnalysisResult] = None
    trend_result_1d: Optional[TrendAnalysisResult] = None
    trend_result_1w: Optional[TrendAnalysisResult] = None
    
    # AOI lists per timeframe
    aois_4h: List[AOIZone] = field(default_factory=list)
    aois_1d: List[AOIZone] = field(default_factory=list)
    
    # Last update times (for debugging/logging)
    last_4h_update: Optional[datetime] = None
    last_1d_update: Optional[datetime] = None
    last_1w_update: Optional[datetime] = None
    
    def get_trend_snapshot(self) -> Mapping[str, Optional[TrendDirection]]:
        """Get trend values as a mapping for production functions."""
        return {
            "4H": self.trend_4h,
            "1D": self.trend_1d,
            "1W": self.trend_1w,
        }
    
    def get_overall_trend(self) -> Optional[TrendDirection]:
        """Determine overall trend using production logic.
        
        Uses get_overall_trend_from_values from trend.bias module
        which implements the middle/consensus trend algorithm.
        """
        return get_overall_trend_from_values(
            self.get_trend_snapshot(),
            TREND_ALIGNMENT_TIMEFRAMES,
        )
    
    def get_tradable_aois(self) -> List[AOIZone]:
        """Get all tradable AOIs from both 4H and 1D timeframes."""
        return [
            aoi for aoi in (self.aois_4h + self.aois_1d)
            if aoi.classification == "tradable"
        ]
    
    def get_trend_alignment_strength(self, direction: TrendDirection) -> int:
        """Count how many timeframes align with the given direction.
        
        Uses calculate_trend_alignment_strength from trend.bias module.
        """
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
    
    @property
    def state(self) -> SymbolState:
        """Get current market state."""
        return self._state
    
    def update_state(self, current_time: datetime) -> None:
        """Update market state based on new timeframe closes.
        
        Checks for new 4H/1D/1W closes and recomputes the corresponding
        trend and AOI states when needed.
        
        Args:
            current_time: Current simulation time (1H candle close)
        """
        # Detect which timeframes have new closes
        close_flags = self._aligner.detect_new_closes(current_time)
        
        # Update 4H state if new 4H candle closed
        if close_flags.new_4h:
            self._update_4h_state(current_time)
        
        # Update 1D state if new 1D candle closed
        if close_flags.new_1d:
            self._update_1d_state(current_time)
        
        # Update 1W state if new 1W candle closed
        if close_flags.new_1w:
            self._update_1w_state(current_time)
    
    def _update_4h_state(self, as_of_time: datetime) -> None:
        """Recompute 4H trend and AOIs."""
        # Get 4H candles for trend analysis
        trend_candles = get_candles_for_analysis(
            self._store, TIMEFRAME_4H, as_of_time, LOOKBACK_4H
        )
        
        if trend_candles is not None and not trend_candles.empty:
            self._state.trend_result_4h = self._compute_trend(trend_candles)
            self._state.trend_4h = (
                self._state.trend_result_4h.trend
                if self._state.trend_result_4h else None
            )
        
        # Get 4H candles for AOI analysis (may need more lookback)
        aoi_candles = get_candles_for_analysis(
            self._store, TIMEFRAME_4H, as_of_time, LOOKBACK_AOI_4H
        )
        
        if aoi_candles is not None and not aoi_candles.empty:
            self._state.aois_4h = self._compute_aois(
                TIMEFRAME_4H, aoi_candles, self._state.get_overall_trend()
            )
        
        self._state.last_4h_update = as_of_time
    
    def _update_1d_state(self, as_of_time: datetime) -> None:
        """Recompute 1D trend and AOIs."""
        # Get 1D candles for trend analysis
        trend_candles = get_candles_for_analysis(
            self._store, TIMEFRAME_1D, as_of_time, LOOKBACK_1D
        )
        
        if trend_candles is not None and not trend_candles.empty:
            self._state.trend_result_1d = self._compute_trend(trend_candles)
            self._state.trend_1d = (
                self._state.trend_result_1d.trend
                if self._state.trend_result_1d else None
            )
        
        # Get 1D candles for AOI analysis
        aoi_candles = get_candles_for_analysis(
            self._store, TIMEFRAME_1D, as_of_time, LOOKBACK_AOI_1D
        )
        
        if aoi_candles is not None and not aoi_candles.empty:
            self._state.aois_1d = self._compute_aois(
                TIMEFRAME_1D, aoi_candles, self._state.get_overall_trend()
            )
        
        self._state.last_1d_update = as_of_time
    
    def _update_1w_state(self, as_of_time: datetime) -> None:
        """Recompute 1W trend (no AOIs for weekly)."""
        trend_candles = get_candles_for_analysis(
            self._store, TIMEFRAME_1W, as_of_time, LOOKBACK_1W
        )
        
        if trend_candles is not None and not trend_candles.empty:
            self._state.trend_result_1w = self._compute_trend(trend_candles)
            self._state.trend_1w = (
                self._state.trend_result_1w.trend
                if self._state.trend_result_1w else None
            )
        
        self._state.last_1w_update = as_of_time
    
    def _compute_trend(self, candles: pd.DataFrame) -> Optional[TrendAnalysisResult]:
        """Compute trend from candles using production logic."""
        if candles is None or candles.empty or "close" not in candles.columns:
            return None
        
        prices = candles["close"].values
        if len(prices) < 2:
            return None
        
        # Get analysis params (using 4H defaults for prominence/distance)
        try:
            params = require_analysis_params(TIMEFRAME_4H)
            distance = params.distance
            prominence = params.prominence
        except KeyError:
            distance = 1
            prominence = 0.0004
        
        swings = get_swing_points(prices, distance, prominence)
        return analyze_snake_trend(swings)
    
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

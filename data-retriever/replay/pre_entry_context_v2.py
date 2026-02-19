"""Pre-entry context V2 computation for replay.

Computes market environment metrics strictly before the entry candle.
Captures location (HTF range positions), maturity (trend age), regime (session bias),
and space (distance to obstacles) factors.

Design principles:
- Use most recently closed HTF candles (daily/weekly)
- All distances normalized by 1H ATR
- Direction-aware metrics (positive = favorable)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

from models import TrendDirection
from trend.structure import SwingPoint, SWING_HIGH, SWING_LOW

from .config import (
    PRE_ENTRY_V2_IMPULSE_THRESHOLD_ATR,
    PRE_ENTRY_V2_LARGE_BAR_MULTIPLIER,
    PRE_ENTRY_V2_IMPULSE_LOOKBACK,
    SESSION_ASIA_START,
    SESSION_ASIA_END,
    SESSION_LONDON_START,
    SESSION_LONDON_END,
    SESSION_NY_START,
    SESSION_NY_END,
    ACTIVE_PROFILE,
)
from trend.structure import get_swing_points, SwingPoint
from configuration import require_analysis_params
from utils.indicators import calculate_atr

if TYPE_CHECKING:
    from .candle_store import CandleStore
    from .market_state import SymbolState


@dataclass
class PreEntryContextV2Data:
    """Pre-entry market environment metrics computed at replay time."""
    
    # HTF Range Position
    htf_range_position_mid: Optional[float] = None
    htf_range_position_high: Optional[float] = None
    
    # Distance to HTF Boundaries
    distance_to_mid_tf_high_atr: Optional[float] = None
    distance_to_mid_tf_low_atr: Optional[float] = None
    distance_to_high_tf_high_atr: Optional[float] = None
    distance_to_high_tf_low_atr: Optional[float] = None
    distance_to_low_tf_high_atr: Optional[float] = None
    distance_to_low_tf_low_atr: Optional[float] = None
    distance_to_next_htf_obstacle_atr: Optional[float] = None
    
    # Session Context
    prev_session_high: Optional[float] = None
    prev_session_low: Optional[float] = None
    distance_to_prev_session_high_atr: Optional[float] = None
    distance_to_prev_session_low_atr: Optional[float] = None
    
    # Trend Maturity
    trend_age_bars_1h: Optional[int] = None
    trend_age_impulses: Optional[int] = None
    recent_trend_payoff_atr_24h: Optional[float] = None
    recent_trend_payoff_atr_48h: Optional[float] = None
    
    # Session Directional Bias
    session_directional_bias: Optional[float] = None
    
    # AOI Freshness
    aoi_time_since_last_touch: Optional[int] = None
    aoi_last_reaction_strength: Optional[float] = None
    
    # Momentum Chase
    distance_from_last_impulse_atr: Optional[float] = None
    
    # HTF Range Size (compressed vs expanded markets)
    htf_range_size_mid_atr: Optional[float] = None
    htf_range_size_high_atr: Optional[float] = None
    
    # AOI Position Inside HTF Range
    aoi_midpoint_range_position_mid: Optional[float] = None
    aoi_midpoint_range_position_high: Optional[float] = None
    
    # Break Candle Metrics
    break_impulse_range_atr: Optional[float] = None      # (high - low) / atr_1h
    break_impulse_body_atr: Optional[float] = None       # abs(close - open) / atr_1h
    break_close_location: Optional[float] = None         # bullish: (close-low)/(high-low), bearish: (high-close)/(high-low)
    
    # Retest Candle Metrics
    retest_candle_body_penetration: Optional[float] = None  # combined body ratio and penetration depth

    # HTF Trend Quality Metrics
    htf_slope_strength_low: Optional[float] = None
    htf_slope_strength_mid: Optional[float] = None
    htf_slope_strength_high: Optional[float] = None
    
    htf_impulse_ratio_low: Optional[float] = None
    htf_impulse_ratio_mid: Optional[float] = None
    htf_impulse_ratio_high: Optional[float] = None
    
    htf_struct_eff_low: Optional[float] = None
    htf_struct_eff_mid: Optional[float] = None
    htf_struct_eff_high: Optional[float] = None

    # AOI Geometry Metrics
    aoi_height_atr: Optional[float] = None
    aoi_entry_depth: Optional[float] = None
    aoi_compression_ratio: Optional[float] = None

    # Break Candle Metrics
    break_def_dist_from_balance_atr: Optional[float] = None
    break_def_liquidity_sweep: Optional[bool] = None

    # After-Break Candle Metrics
    after_break_pullback_depth_atr: Optional[float] = None
    after_break_close_dist_edge_atr: Optional[float] = None
    after_break_range_compress_ratio: Optional[float] = None
    after_break_range_compress_ratio: Optional[float] = None
    after_break_retest_fail_flag: Optional[bool] = None

    # Session Dynamics
    session_transition_prox_flag: Optional[bool] = None
    session_align_break_low: Optional[bool] = None
    session_align_break_mid: Optional[bool] = None
    session_align_break_mid: Optional[bool] = None
    session_align_break_high: Optional[bool] = None

    # Path-Risk Context
    dist_nearest_opposing_liq_atr: Optional[float] = None
    structure_density_behind_entry: Optional[float] = None
    
    # New Features
    day_range_atr: Optional[float] = None
    opposing_wick_ratio: Optional[float] = None




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


def _to_python_bool(value) -> Optional[bool]:
    """Convert numpy types/int to native Python bool for DB compatibility."""
    if value is None:
        return None
    return bool(value)


class PreEntryContextV2Calculator:
    """Computes pre-entry market environment metrics from candle data.
    
    All computations use candles strictly before the entry candle.
    """
    
    def __init__(
        self,
        candle_store: "CandleStore",
        signal_time: datetime,
        retest_time: datetime,
        direction: TrendDirection,
        entry_price: float,
        atr_1h: float,
        aoi_low: float,
        aoi_high: float,
        aoi_timeframe: str,
        state: "SymbolState",
        is_break_candle_last: bool,  # New param
        break_candle: Optional[dict] = None,      # {open, high, low, close}
        retest_candle: Optional[dict] = None,     # {open, high, low, close}
    ):
        self._store = candle_store
        self._signal_time = signal_time
        self._retest_time = retest_time
        self._direction = direction
        self._entry_price = entry_price
        self._atr_1h = atr_1h
        self._aoi_low = aoi_low
        self._aoi_high = aoi_high
        self._aoi_timeframe = aoi_timeframe
        self._state = state
        self._is_long = direction == TrendDirection.BULLISH
        self._is_break_candle_last = is_break_candle_last
        self._break_candle = break_candle
        self._retest_candle = retest_candle
    
    def compute(self) -> Optional[PreEntryContextV2Data]:
        """Compute all pre-entry market environment metrics.
        
        Returns:
            PreEntryContextV2Data with all computed metrics, or None if insufficient data.
        """
        if self._atr_1h <= 0:
            return None
        
        # Get candles strictly before signal time
        candles_1h = self._store.get_1h_candles().get_candles_up_to(self._signal_time)
        if candles_1h is None or candles_1h.empty:
            return None
        
        candles_before = candles_1h[candles_1h["time"] < self._signal_time].copy()
        if len(candles_before) < 48:  # Need at least 48h of history
            return None
        
        # Compute all metric groups
        htf_range = self._compute_htf_range_positions()
        htf_distances = self._compute_htf_distances()
        session_metrics = self._compute_session_metrics(candles_before)
        trend_maturity = self._compute_trend_maturity(candles_before)
        session_bias = self._compute_session_directional_bias(candles_before)
        aoi_freshness = self._compute_aoi_freshness(candles_before)
        momentum = self._compute_momentum_chase(candles_before)
        htf_range_size = self._compute_htf_range_size()
        aoi_position = self._compute_aoi_position_in_htf_range()
        
        return PreEntryContextV2Data(
            # HTF Range Position
            htf_range_position_mid=_to_python_float(htf_range.get("daily")),
            htf_range_position_high=_to_python_float(htf_range.get("weekly")),
            # HTF Distances
            distance_to_mid_tf_high_atr=_to_python_float(htf_distances.get("daily_high")),
            distance_to_mid_tf_low_atr=_to_python_float(htf_distances.get("daily_low")),
            distance_to_high_tf_high_atr=_to_python_float(htf_distances.get("weekly_high")),
            distance_to_high_tf_low_atr=_to_python_float(htf_distances.get("weekly_low")),
            distance_to_low_tf_high_atr=_to_python_float(htf_distances.get("4h_high")),
            distance_to_low_tf_low_atr=_to_python_float(htf_distances.get("4h_low")),
            distance_to_next_htf_obstacle_atr=_to_python_float(htf_distances.get("next_obstacle")),
            # Session
            prev_session_high=_to_python_float(session_metrics.get("high")),
            prev_session_low=_to_python_float(session_metrics.get("low")),
            distance_to_prev_session_high_atr=_to_python_float(session_metrics.get("dist_high")),
            distance_to_prev_session_low_atr=_to_python_float(session_metrics.get("dist_low")),
            # Trend Maturity
            trend_age_bars_1h=_to_python_int(trend_maturity.get("age_bars")),
            trend_age_impulses=_to_python_int(trend_maturity.get("impulses")),
            recent_trend_payoff_atr_24h=_to_python_float(trend_maturity.get("payoff_24h")),
            recent_trend_payoff_atr_48h=_to_python_float(trend_maturity.get("payoff_48h")),
            # Session Bias
            session_directional_bias=_to_python_float(session_bias),
            # AOI Freshness
            aoi_time_since_last_touch=_to_python_int(aoi_freshness.get("bars_since")),
            aoi_last_reaction_strength=_to_python_float(aoi_freshness.get("reaction")),
            # Momentum
            distance_from_last_impulse_atr=_to_python_float(momentum),
            # HTF Range Size
            htf_range_size_mid_atr=_to_python_float(htf_range_size.get("daily")),
            htf_range_size_high_atr=_to_python_float(htf_range_size.get("weekly")),
            # AOI Position in HTF Range
            aoi_midpoint_range_position_mid=_to_python_float(aoi_position.get("daily")),
            aoi_midpoint_range_position_high=_to_python_float(aoi_position.get("weekly")),
            # Break Candle Metrics
            break_impulse_range_atr=_to_python_float(self._compute_break_impulse_range()),
            break_impulse_body_atr=_to_python_float(self._compute_break_impulse_body()),
            break_close_location=_to_python_float(self._compute_break_close_location()),
            # Retest Candle Metrics
            retest_candle_body_penetration=_to_python_float(self._compute_retest_body_penetration()),
            
            # HTF Trend Quality Metrics
            htf_slope_strength_low=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_low, self._state.trend_low).get("slope")),
            htf_slope_strength_mid=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_mid, self._state.trend_mid).get("slope")),
            htf_slope_strength_high=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_high, self._state.trend_high).get("slope")),
            
            htf_impulse_ratio_low=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_low, self._state.trend_low).get("impulse_ratio")),
            htf_impulse_ratio_mid=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_mid, self._state.trend_mid).get("impulse_ratio")),
            htf_impulse_ratio_high=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_high, self._state.trend_high).get("impulse_ratio")),
            
            htf_struct_eff_low=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_low, self._state.trend_low).get("struct_eff")),
            htf_struct_eff_mid=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_mid, self._state.trend_mid).get("struct_eff")),
            htf_struct_eff_high=_to_python_float(self._compute_htf_quality_metrics(ACTIVE_PROFILE.trend_tf_high, self._state.trend_high).get("struct_eff")),
            
            # AOI Geometry
            aoi_height_atr=_to_python_float(self._compute_aoi_height_atr()),
            aoi_entry_depth=_to_python_float(self._compute_aoi_entry_depth()),
            aoi_compression_ratio=_to_python_float(self._compute_aoi_compression_ratio()),
            
            # Break Candle Metrics (Only if is_break_candle_last=True)
            break_def_dist_from_balance_atr=_to_python_float(self._compute_break_metrics().get("dist_balance")) if self._is_break_candle_last else None,
            break_def_liquidity_sweep=_to_python_bool(self._compute_break_metrics().get("sweep")) if self._is_break_candle_last else None,
            
            # After-Break Metrics (Only if is_break_candle_last=False)
            after_break_pullback_depth_atr=_to_python_float(self._compute_after_break_metrics().get("pullback_depth")) if not self._is_break_candle_last else None,
            after_break_close_dist_edge_atr=_to_python_float(self._compute_after_break_metrics().get("dist_edge")) if not self._is_break_candle_last else None,
            after_break_range_compress_ratio=_to_python_float(self._compute_after_break_metrics().get("compression_ratio")) if not self._is_break_candle_last else None,

            after_break_retest_fail_flag=_to_python_bool(self._compute_after_break_metrics().get("retest_fail")) if not self._is_break_candle_last else None,

            # Session Dynamics
            session_transition_prox_flag=_to_python_bool(self._compute_session_transition_flag()),
            session_align_break_low=_to_python_bool(self._compute_session_alignment(ACTIVE_PROFILE.trend_tf_low)),
            session_align_break_mid=_to_python_bool(self._compute_session_alignment(ACTIVE_PROFILE.trend_tf_mid)),
            session_align_break_high=_to_python_bool(self._compute_session_alignment(ACTIVE_PROFILE.trend_tf_high)),
            
            # Path-Risk Context
            dist_nearest_opposing_liq_atr=_to_python_float(self._compute_path_risk_metrics().get("dist_liq")),
            structure_density_behind_entry=_to_python_float(self._compute_path_risk_metrics().get("density")),
            
            # New Features
            day_range_atr=_to_python_float(self._compute_day_range_atr()),
            opposing_wick_ratio=_to_python_float(self._compute_opposing_wick_ratio()),
        )
    
    def _compute_aoi_height_atr(self) -> Optional[float]:
        """Compute AOI height in ATR units."""
        if self._atr_1h <= 0:
            return None
        height = self._aoi_high - self._aoi_low
        return height / self._atr_1h

    def _compute_aoi_entry_depth(self) -> Optional[float]:
        """Compute entry depth inside AOI (0.0=Edge, 1.0=Other Edge)."""
        height = self._aoi_high - self._aoi_low
        if height <= 0:
            return None
            
        if self._is_long:
            # Bullish: Depth measured from Low up to High
            # (entry_price - aoi_low) / height
            return (self._entry_price - self._aoi_low) / height
        else:
            # Bearish: Depth measured from High down to Low
            # (aoi_high - entry_price) / height
            return (self._aoi_high - self._entry_price) / height

    def _compute_aoi_compression_ratio(self) -> Optional[float]:
        """Compute compression ratio: AOI Height ATR / Avg 4H Candle Range ATR."""
        aoi_height_atr = self._compute_aoi_height_atr()
        if aoi_height_atr is None:
            return None
            
        # Get last 20 completed low-TF candles
        candles_4h = self._store.get(ACTIVE_PROFILE.trend_tf_low).get_candles_up_to(self._signal_time)
        if candles_4h is None or len(candles_4h) == 0:
             return None
             
        # Filter strictly before signal
        candles = candles_4h[candles_4h["time"] < self._signal_time].tail(20)
        if len(candles) < 20:
             # User specified "over the last 20 completed 4H candles". 
             # If we don't have 20, should we return None?
             # Probably safer to return None or calculate on available.
             # Strict compliance = return None if < 20.
             return None
             
        # Calculate Average 4H Candle Range in ATR
        # User defined: Mean of (High - Low) / atr_1h_at_signal_time
        ranges = candles["high"] - candles["low"]
        avg_range = ranges.mean()
        
        if self._atr_1h <= 0: 
             return None
             
        avg_range_atr = avg_range / self._atr_1h
        
        if avg_range_atr <= 0:
             return None
             
        return aoi_height_atr / avg_range_atr
    
    def _compute_break_metrics(self) -> dict:
        """Compute metrics specific to the Break Candle."""
        result = {"dist_balance": None, "sweep": None}
        if self._atr_1h <= 0 or not self._break_candle:
            return result

        # 1. Distance from Recent Balance (Mean of last 20 closes before break)
        # Strategy: Get 1H candles up to signal.
        candles = self._store.get_1h_candles().get_candles_up_to(self._signal_time)
        if candles is None or len(candles) < 22: # Need 20 + break + buffer
            return result
        
        # Last 20 candles BEFORE break.
        # If break is -1, then slice [-21 : -1]
        pre_break_candles = candles.iloc[-21:-1]
        if len(pre_break_candles) < 20: 
             return result
             
        balance_price = pre_break_candles["close"].mean()
        raw_diff = self._entry_price - balance_price
        
        if self._is_long:
            result["dist_balance"] = raw_diff / self._atr_1h
        else:
            result["dist_balance"] = -raw_diff / self._atr_1h
            
        # 2. Liquidity Sweep Flag
        # Most recent external swing before break.
        # Scan ample history (e.g. 200 bars).
        scan_candles = candles.iloc[-200:-1] 
        if len(scan_candles) < 20:
             return result
        
        try:
             prices = scan_candles["close"].values 
             swings = get_swing_points(prices, distance=5, prominence=0.0004) # 1H params assumption
             
             if not swings: 
                 return result
                 
             last_swing = None
             if self._is_long:
                 for s in reversed(swings):
                     if s.kind == SWING_HIGH:
                         last_swing = s
                         break
             else:
                 for s in reversed(swings):
                     if s.kind == SWING_LOW:
                         last_swing = s
                         break
                         
             if last_swing:
                 break_h = self._break_candle["high"]
                 break_l = self._break_candle["low"]
                 
                 if self._is_long:
                     result["sweep"] = break_h > last_swing.price
                 else:
                     result["sweep"] = break_l < last_swing.price
                     
        except Exception:
            pass

        return result

    def _compute_after_break_metrics(self) -> dict:
        """Compute metrics for the After-Break period (Signal is After-Break or later)."""
        result = {
            "pullback_depth": None, 
            "dist_edge": None, 
            "compression_ratio": None, 
            "retest_fail": None
        }
        
        candles = self._store.get_1h_candles().get_candles_up_to(self._signal_time)
        if candles is None or len(candles) < 22:
            return result
            
        after_break_candle = candles.iloc[-1]
        
        # 1. Pullback Depth
        if self._is_long:
            depth = (after_break_candle["open"] - after_break_candle["low"]) / self._atr_1h
        else:
            depth = (after_break_candle["high"] - after_break_candle["open"]) / self._atr_1h
        result["pullback_depth"] = depth
        
        # 2. Close Distance from Edge
        if self._is_long:
            dist = (after_break_candle["close"] - self._aoi_high) / self._atr_1h
        else:
            dist = (self._aoi_low - after_break_candle["close"]) / self._atr_1h
        result["dist_edge"] = dist
        
        # 3. Range Compression Ratio
        prev_20 = candles.iloc[-21:-1]
        if len(prev_20) == 20:
             # Ranges normalized by CURRENT ATR
             ranges_atr = (prev_20["high"] - prev_20["low"]) / self._atr_1h
             avg_range_atr = ranges_atr.mean()
             
             current_range_atr = (after_break_candle["high"] - after_break_candle["low"]) / self._atr_1h
             
             if avg_range_atr > 0:
                 result["compression_ratio"] = current_range_atr / avg_range_atr
                 
        # 4. Retest Failure Flag
        ab_high = after_break_candle["high"]
        ab_low = after_break_candle["low"]
        ab_close = after_break_candle["close"]
        
        if self._is_long:
            touched = ab_low <= self._aoi_high
            closed_outside = ab_close > self._aoi_high
            result["retest_fail"] = touched and closed_outside
        else:
            touched = ab_high >= self._aoi_low
            closed_outside = ab_close < self._aoi_low
            result["retest_fail"] = touched and closed_outside
            
        return result

    def _get_session_bucket(self, hour: int) -> str:
        """Get session bucket from UTC hour (Duplicate of SignalDetector logic for consistency)."""
        if 4 <= hour <= 6:
            return "pre_london"
        elif 7 <= hour <= 11:
            return "london"
        elif 12 <= hour <= 16:
            return "ny"
        else:
            return "post_ny"

    def _compute_session_transition_flag(self) -> bool:
        """Check if signal time is within 2 hours of session boundaries (07:00 and 12:00)."""
        # Boundaries: London Open (7), NY Open (12).
        # X = 2 hours.
        h = self._signal_time.hour
        
        # Check proximity to 7
        dist_7 = abs(h - 7)
        if dist_7 <= 2:
            return True
            
        # Check proximity to 12
        dist_12 = abs(h - 12)
        if dist_12 <= 2:
            return True
            
        return False

    def _compute_session_alignment(self, timeframe: str) -> Optional[bool]:
        """Check if HTF break happened in same session bucket as signal."""
        break_time = None
        break_time = self._state.break_times.get(timeframe)
            
        if not break_time:
            return None
            
        break_bucket = self._get_session_bucket(break_time.hour)
        signal_bucket = self._get_session_bucket(self._signal_time.hour)
        
        return break_bucket == signal_bucket

    def _compute_path_risk_metrics(self) -> dict:
        """Compute Path-Risk Context metrics."""
        result = {"dist_liq": None, "density": None}
        if self._atr_1h <= 0:
            return result
            
        candles = self._store.get_1h_candles().get_candles_up_to(self._signal_time)
        
        # 1. Distance to Nearest Opposing Liquidity
        # Lookback 200 bars to find nearest swing.
        if candles is None or len(candles) < 20:
            return result
            
        scan_len = 200
        scan_candles = candles.iloc[-scan_len:-1] if len(candles) > scan_len else candles.iloc[:-1]
        
        if len(scan_candles) < 5:
            return result
            
        try:
            prices = scan_candles["close"].values
            # Using standard 1H swing params (assumed 5, 0.0004 from earlier code)
            swings = get_swing_points(prices, distance=5, prominence=0.0004)
            
            nearest_dist = None
            
            if self._is_long:
                # Find nearest Swing Low below entry price for "Opposing Liquidity"? 
                # WAIT. User Requirements:
                # "For bullish trades... nearest confirmed swing LOW below entry."
                # RE-READ CAREFULLY: "Distance to nearest opposing liquidity pool"
                # usually means Target (Resistance for Long).
                # BUT user explicitly defined: "For bullish trades, compute ATR-normalized distance from entry_price to the nearest confirmed swing LOW below entry."
                # AND "Structure density... count swing LOWs below entry".
                # OK, I will follow the Explicit Definition: Distance to Swing Low < Entry (Support).
                
                # Check for Swing Low < Entry
                valid_swings = [s for s in swings if s.kind == SWING_LOW and s.price < self._entry_price]
                if valid_swings:
                    # Nearest in PRICE or TIME? Usually "Nearest Opposing Liquidity" implies Price distance.
                    # "Distance from entry_price to..." -> implies Price delta.
                    # We want the one closest to entry price (highest valid low).
                    best_swing = max(valid_swings, key=lambda s: s.price)
                    nearest_dist = abs(self._entry_price - best_swing.price) / self._atr_1h
            else:
                # Bearish: Nearest Swing High > Entry
                valid_swings = [s for s in swings if s.kind == SWING_HIGH and s.price > self._entry_price]
                if valid_swings:
                    # Closest to entry is the lowest valid high.
                    best_swing = min(valid_swings, key=lambda s: s.price)
                    nearest_dist = abs(best_swing.price - self._entry_price) / self._atr_1h
                    
            result["dist_liq"] = nearest_dist
            
            # 2. Structure Density
            # "Count number of confirmed swing LOWs below entry_price within the last 50 completed 1H candles."
            density_lookback = 50
            density_subset = candles.iloc[-density_lookback:-1] if len(candles) > density_lookback else candles.iloc[:-1]
            if len(density_subset) > 5:
                 d_prices = density_subset["close"].values
                 d_swings = get_swing_points(d_prices, distance=5, prominence=0.0004)
                 
                 count = 0
                 if self._is_long:
                     # Count Swing Lows < Entry
                     count = sum(1 for s in d_swings if s.kind == SWING_LOW and s.price < self._entry_price)
                 else:
                     # Count Swing Highs > Entry
                     count = sum(1 for s in d_swings if s.kind == SWING_HIGH and s.price > self._entry_price)
                     
                 result["density"] = count / 50.0
                 
        except Exception:
            pass
            
        return result

    def _compute_htf_quality_metrics(self, timeframe: str, trend_direction: Optional[TrendDirection]) -> dict:
        """Compute slope strength, impulse ratio, and structural efficiency for a timeframe."""
        result = {"slope": None, "impulse_ratio": None, "struct_eff": None}
        
        if not trend_direction:
            return result
            
        # Get candles for structure analysis
        lookback = ACTIVE_PROFILE.lookback_for_trend(timeframe) * 2
        tf_candles = self._store.get(timeframe).get_candles_up_to(self._signal_time)
            
        if tf_candles is None or len(tf_candles) < 20: 
            return result
            
        # Filter to relevant history before signal
        candles = tf_candles[tf_candles["time"] < self._signal_time].copy()
        if len(candles) < 20:
            return result

        # Compute ATR at signal time for normalization
        current_atr = calculate_atr(candles, length=14)
        if current_atr <= 0:
            return result
            
        # Get swings
        try:
            params = require_analysis_params(timeframe)
            distance = params.distance
            prominence = params.prominence
        except KeyError:
            distance = 1
            prominence = 0.0004
            
        prices = candles["close"].values
        swings = get_swing_points(prices, distance, prominence)
        
        # 1. Slope Strength
        result["slope"] = self._calculate_slope_strength(swings, current_atr)
        
        # 2. Impulse Ratio & 3. Structural Efficiency (require completed impulse)
        impulse_data = self._identify_last_completed_impulse(swings, candles, trend_direction)
        if impulse_data:
            range_impulse, range_correction, start_swing, end_swing = impulse_data
            
            # Impulse Ratio
            if range_correction >= 0.3 * current_atr:
                 ratio = (range_impulse / current_atr) / (range_correction / current_atr)
                 result["impulse_ratio"] = ratio
                 
            # Structural Efficiency
            result["struct_eff"] = self._calculate_structural_efficiency(
                start_swing, end_swing, candles, current_atr, trend_direction
            )
            
        return result

    def _calculate_slope_strength(self, swings: list[SwingPoint], atr: float) -> Optional[float]:
        """Linear regression slope of last 5 swings."""
        if len(swings) < 5:
            return None
            
        relevant_swings = swings[-5:]
        
        x = np.array(range(5))
        y = np.array([s.price / atr for s in relevant_swings])
        
        try:
            slope, _ = np.polyfit(x, y, 1)
            return float(slope)
        except:
            return None

    def _identify_last_completed_impulse(
        self, 
        swings: list[SwingPoint], 
        candles: pd.DataFrame, 
        trend: TrendDirection
    ) -> Optional[tuple[float, float, SwingPoint, SwingPoint]]:
        """Identify last completed impulse and preceeding correction ranges."""
        if len(swings) < 3:
            return None
            
        is_bullish = trend == TrendDirection.BULLISH
        
        # Scan backwards for sequence: Pivot A -> Pivot B (Correction) -> Pivot C (Impulse)
        for i in range(len(swings) - 1, 1, -1):
            c = swings[i]
            b = swings[i-1]
            a = swings[i-2]
            
            is_impulse = False
            if is_bullish:
                # Expect B=Low, C=High (Impulse Up)
                if b.kind == "L" and c.kind == "H":
                    if c.price > b.price:
                         is_impulse = True
            else: # Bearish
                # Expect B=High, C=Low (Impulse Down)
                if b.kind == "H" and c.kind == "L":
                    if c.price < b.price:
                        is_impulse = True
                        
            if is_impulse:
                range_impulse = abs(c.price - b.price)
                range_correction = abs(b.price - a.price)
                return range_impulse, range_correction, b, c
                
        return None

    def _calculate_structural_efficiency(
        self, 
        start_swing: SwingPoint, 
        end_swing: SwingPoint, 
        candles: pd.DataFrame, 
        atr: float,
        trend: TrendDirection
    ) -> Optional[float]:
        """MFE / max(|MAE|, 0.5) for the impulse start_swing -> end_swing."""
        start_idx = start_swing.index
        end_idx = end_swing.index
        
        if start_idx >= end_idx or end_idx >= len(candles):
            return None
            
        impulse_candles = candles.iloc[start_idx : end_idx + 1]
        
        if len(impulse_candles) == 0:
            return None
            
        start_price = start_swing.price
        is_bullish = trend == TrendDirection.BULLISH
        
        if is_bullish:
            max_h_val = impulse_candles["high"].max()
            mfe_atr = (max_h_val - start_price) / atr
            
            # Find index of first max_h
            highs = impulse_candles["high"].values
            lows = impulse_candles["low"].values
            mfe_idx_rel = np.argmax(highs)
            
            pre_mfe_lows = lows[:mfe_idx_rel + 1]
            if len(pre_mfe_lows) > 0:
                min_l_val = np.min(pre_mfe_lows)
                # Ensure MAE is negative if it goes against us, positive otherwise? 
                # MAE logic usually: Price - Low (Bullish). If Low < Price, result is positive distance against us?
                # User said: "max(|MAE_ATR|, 0.5)".
                # Standard MAE: Drawdown.
                # Bullish: Entry - Low.
                mae_atr = (start_price - min_l_val) / atr
            else:
                mae_atr = 0.0
                
        else:
             lows = impulse_candles["low"].values
             highs = impulse_candles["high"].values
             
             min_l_val = np.min(lows)
             mfe_atr = (start_price - min_l_val) / atr
             
             mfe_idx_rel = np.argmin(lows)
             
             pre_mfe_highs = highs[:mfe_idx_rel + 1]
             if len(pre_mfe_highs) > 0:
                 max_h_val = np.max(pre_mfe_highs)
                 mae_atr = (max_h_val - start_price) / atr
             else:
                 mae_atr = 0.0

        denom = max(abs(mae_atr), 0.5)
        return mfe_atr / denom
    
    def _compute_htf_range_positions(self) -> dict:
        """Compute position within daily and weekly ranges.
        
        Uses most recently closed daily/weekly candle.
        """
        result = {}
        
        # Get last closed mid-TF candle
        daily_candles = self._store.get(ACTIVE_PROFILE.trend_tf_mid).get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) > 0:
            last_daily = daily_candles.iloc[-1]
            daily_high = float(last_daily["high"])
            daily_low = float(last_daily["low"])
            daily_range = daily_high - daily_low
            if daily_range > 0:
                result["daily"] = (self._entry_price - daily_low) / daily_range
        
        # Get last closed high-TF candle
        weekly_candles = self._store.get(ACTIVE_PROFILE.trend_tf_high).get_candles_up_to(self._signal_time)
        if weekly_candles is not None and len(weekly_candles) > 0:
            last_weekly = weekly_candles.iloc[-1]
            weekly_high = float(last_weekly["high"])
            weekly_low = float(last_weekly["low"])
            weekly_range = weekly_high - weekly_low
            if weekly_range > 0:
                result["weekly"] = (self._entry_price - weekly_low) / weekly_range
        
        return result
    
    def _compute_htf_distances(self) -> dict:
        """Compute distances to 4H/daily/weekly high/low in ATR units."""
        result = {}
        
        # Get last closed low-TF candle
        candles_4h = self._store.get(ACTIVE_PROFILE.trend_tf_low).get_candles_up_to(self._signal_time)
        if candles_4h is not None and len(candles_4h) > 0:
            last_4h = candles_4h.iloc[-1]
            h4_high = float(last_4h["high"])
            h4_low = float(last_4h["low"])
            
            result["4h_high"] = abs(h4_high - self._entry_price) / self._atr_1h
            result["4h_low"] = abs(self._entry_price - h4_low) / self._atr_1h
        
        # Get last closed mid-TF candle
        daily_candles = self._store.get(ACTIVE_PROFILE.trend_tf_mid).get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) > 0:
            last_daily = daily_candles.iloc[-1]
            daily_high = float(last_daily["high"])
            daily_low = float(last_daily["low"])
            
            result["daily_high"] = abs(daily_high - self._entry_price) / self._atr_1h
            result["daily_low"] = abs(self._entry_price - daily_low) / self._atr_1h
        
        # Get last closed high-TF candle
        weekly_candles = self._store.get(ACTIVE_PROFILE.trend_tf_high).get_candles_up_to(self._signal_time)
        if weekly_candles is not None and len(weekly_candles) > 0:
            last_weekly = weekly_candles.iloc[-1]
            weekly_high = float(last_weekly["high"])
            weekly_low = float(last_weekly["low"])
            
            result["weekly_high"] = abs(weekly_high - self._entry_price) / self._atr_1h
            result["weekly_low"] = abs(self._entry_price - weekly_low) / self._atr_1h
        
        # Compute next obstacle based on direction (includes 4H, daily, weekly)
        if self._is_long:
            # Long: obstacle is to the upside (highs)
            candidates = [
                result.get("4h_high"),
                result.get("daily_high"),
                result.get("weekly_high"),
            ]
        else:
            # Short: obstacle is to the downside (lows)
            candidates = [
                result.get("4h_low"),
                result.get("daily_low"),
                result.get("weekly_low"),
            ]
        
        valid_candidates = [c for c in candidates if c is not None]
        if valid_candidates:
            result["next_obstacle"] = min(valid_candidates)
        
        return result
    
    def _get_session_window(self, signal_time: datetime) -> tuple[int, int]:
        """Get the session window containing the signal hour."""
        hour = signal_time.hour
        
        if SESSION_ASIA_START <= hour < SESSION_ASIA_END:
            return SESSION_ASIA_START, SESSION_ASIA_END
        elif SESSION_LONDON_START <= hour < SESSION_LONDON_END:
            return SESSION_LONDON_START, SESSION_LONDON_END
        else:
            return SESSION_NY_START, SESSION_NY_END
    
    def _get_previous_session_window(self, signal_time: datetime) -> tuple[datetime, datetime]:
        """Get start and end times of the previous session."""
        current_start, _ = self._get_session_window(signal_time)
        
        # Map current session to previous session times
        signal_date = signal_time.date()
        
        if current_start == SESSION_ASIA_START:
            # Previous = NY (day before)
            prev_date = signal_date - timedelta(days=1)
            start = datetime(prev_date.year, prev_date.month, prev_date.day, 
                           SESSION_NY_START, 0, 0, tzinfo=timezone.utc)
            end = datetime(prev_date.year, prev_date.month, prev_date.day,
                         SESSION_NY_END, 0, 0, tzinfo=timezone.utc)
        elif current_start == SESSION_LONDON_START:
            # Previous = Asia (same day)
            start = datetime(signal_date.year, signal_date.month, signal_date.day,
                           SESSION_ASIA_START, 0, 0, tzinfo=timezone.utc)
            end = datetime(signal_date.year, signal_date.month, signal_date.day,
                         SESSION_ASIA_END, 0, 0, tzinfo=timezone.utc)
        else:  # NY
            # Previous = London (same day)
            start = datetime(signal_date.year, signal_date.month, signal_date.day,
                           SESSION_LONDON_START, 0, 0, tzinfo=timezone.utc)
            end = datetime(signal_date.year, signal_date.month, signal_date.day,
                         SESSION_LONDON_END, 0, 0, tzinfo=timezone.utc)
        
        return start, end
    
    def _compute_session_metrics(self, candles: pd.DataFrame) -> dict:
        """Compute previous session high/low and distances."""
        result = {}
        
        prev_start, prev_end = self._get_previous_session_window(self._signal_time)
        
        # Filter candles to previous session
        session_candles = candles[
            (candles["time"] >= prev_start) & (candles["time"] < prev_end)
        ]
        
        if len(session_candles) == 0:
            return result
        
        session_high = float(session_candles["high"].max())
        session_low = float(session_candles["low"].min())
        
        result["high"] = session_high
        result["low"] = session_low
        result["dist_high"] = abs(session_high - self._entry_price) / self._atr_1h
        result["dist_low"] = abs(self._entry_price - session_low) / self._atr_1h
        
        return result
    
    def _compute_trend_maturity(self, candles: pd.DataFrame) -> dict:
        """Compute trend age and payoff metrics.
        
        trend_age_bars_1h: Bars since trend_alignment >= 2 in current direction
        trend_age_impulses: Count of directional runs >= threshold ATR
        recent_trend_payoff: Price change over 24h/48h in ATR units
        """
        result = {}
        
        if len(candles) < 2:
            return result
        
        # Recent trend payoff (signed, direction-aware)
        current_close = float(candles.iloc[-1]["close"])
        
        if len(candles) >= 24:
            close_24h_ago = float(candles.iloc[-24]["close"])
            payoff_24h = (current_close - close_24h_ago) / self._atr_1h
            if not self._is_long:
                payoff_24h = -payoff_24h
            result["payoff_24h"] = payoff_24h
        
        if len(candles) >= 48:
            close_48h_ago = float(candles.iloc[-48]["close"])
            payoff_48h = (current_close - close_48h_ago) / self._atr_1h
            if not self._is_long:
                payoff_48h = -payoff_48h
            result["payoff_48h"] = payoff_48h
        
        # Trend age: count bars back until alignment drops below 2
        # This is an approximation - we check current alignment and scan back
        # In a real scenario, we'd need historical alignment data
        trend_alignment = self._state.get_trend_alignment_strength(self._direction)
        if trend_alignment >= 2:
            # Scan backwards to estimate when trend started
            age_bars = self._estimate_trend_age(candles)
            result["age_bars"] = age_bars
        else:
            result["age_bars"] = 0
        
        # Count impulses (directional runs >= threshold ATR)
        impulse_candles = candles.tail(PRE_ENTRY_V2_IMPULSE_LOOKBACK)
        impulse_count = self._count_impulses(impulse_candles)
        result["impulses"] = impulse_count
        
        return result
    
    def _estimate_trend_age(self, candles: pd.DataFrame) -> int:
        """Estimate how many hours the trend has been fully aligned (all 3 TFs).
        
        Logic:
        1. Check if all 3 TFs (4H, 1D, 1W) are currently aligned with direction
        2. If not all aligned, return 0
        3. For each TF, find when the trend flipped to current direction (scanning backwards)
        4. Return hours from the most recent flip to signal_time
        """
        # Check if all 3 TFs are aligned
        if self._state.trend_low != self._direction:
            return 0
        if self._state.trend_mid != self._direction:
            return 0
        if self._state.trend_high != self._direction:
            return 0
        
        # Find when each TF trend flipped to current direction
        flip_time_4h = self._find_trend_flip_time(ACTIVE_PROFILE.trend_tf_low)
        flip_time_1d = self._find_trend_flip_time(ACTIVE_PROFILE.trend_tf_mid)
        flip_time_1w = self._find_trend_flip_time(ACTIVE_PROFILE.trend_tf_high)
        
        # If any flip time is None (no flip found), use a very old time
        flip_times = []
        if flip_time_4h:
            flip_times.append(flip_time_4h)
        if flip_time_1d:
            flip_times.append(flip_time_1d)
        if flip_time_1w:
            flip_times.append(flip_time_1w)
        
        if not flip_times:
            return 0
        
        # The trend age is determined by the most recent flip (latest time = youngest trend)
        most_recent_flip = max(flip_times)
        
        # Calculate hours from flip to signal_time
        hours = (self._signal_time - most_recent_flip).total_seconds() / 3600
        return max(0, int(hours))
    
    def _find_trend_flip_time(self, timeframe: str) -> Optional[datetime]:
        """Find when the trend on a specific TF flipped to the current direction.
        
        Scans backwards through TF candles to find where the trend changed.
        Uses simple higher-highs/lower-lows logic as a proxy for trend.
        """
        # Get candles for the timeframe
        p = ACTIVE_PROFILE
        if timeframe == p.trend_tf_low:
            tf_candles = self._store.get(p.trend_tf_low).get_candles_up_to(self._signal_time)
            lookback = 50
        elif timeframe == p.trend_tf_mid:
            tf_candles = self._store.get(p.trend_tf_mid).get_candles_up_to(self._signal_time)
            lookback = 30
        elif timeframe == p.trend_tf_high:
            tf_candles = self._store.get(p.trend_tf_high).get_candles_up_to(self._signal_time)
            lookback = 20
        else:
            return None
        
        if tf_candles is None or len(tf_candles) < 3:
            return None
        
        # Limit lookback
        tf_candles = tf_candles.tail(lookback)
        
        # Scan backwards to find where trend flipped
        # For bullish: look for where we transitioned from lower-lows to higher-lows
        # For bearish: look for where we transitioned from higher-highs to lower-highs
        for i in range(len(tf_candles) - 2, 1, -1):
            current = tf_candles.iloc[i]
            prev = tf_candles.iloc[i - 1]
            prev2 = tf_candles.iloc[i - 2]
            
            if self._is_long:
                # Bullish: higher lows forming
                current_hl = current["low"] > prev["low"]
                prev_ll = prev["low"] < prev2["low"]
                if prev_ll and current_hl:
                    # Found flip point
                    return pd.Timestamp(current["time"]).to_pydatetime()
            else:
                # Bearish: lower highs forming
                current_lh = current["high"] < prev["high"]
                prev_hh = prev["high"] > prev2["high"]
                if prev_hh and current_lh:
                    # Found flip point
                    return pd.Timestamp(current["time"]).to_pydatetime()
        
        # No flip found in lookback - trend has been established longer
        # Return the earliest candle time as a fallback
        return pd.Timestamp(tf_candles.iloc[0]["time"]).to_pydatetime()
    
    def _count_impulses(self, candles: pd.DataFrame) -> int:
        """Count directional impulse runs in the lookback window.
        
        An impulse is a contiguous run where net movement >= threshold ATR.
        """
        if len(candles) < 2:
            return 0
        
        threshold = PRE_ENTRY_V2_IMPULSE_THRESHOLD_ATR * self._atr_1h
        impulse_count = 0
        current_run = 0.0
        
        for i in range(1, len(candles)):
            prev_close = float(candles.iloc[i - 1]["close"])
            curr_close = float(candles.iloc[i]["close"])
            
            move = curr_close - prev_close
            if not self._is_long:
                move = -move
            
            if move > 0:
                current_run += move
            else:
                # Direction changed, check if run was an impulse
                if current_run >= threshold:
                    impulse_count += 1
                current_run = 0.0
        
        # Check final run
        if current_run >= threshold:
            impulse_count += 1
        
        return impulse_count
    
    def _compute_session_directional_bias(self, candles: pd.DataFrame) -> Optional[float]:
        """Compute current session bias: (session_close - session_open) / ATR."""
        current_start, current_end = self._get_session_window(self._signal_time)
        
        signal_date = self._signal_time.date()
        session_start = datetime(signal_date.year, signal_date.month, signal_date.day,
                                current_start, 0, 0, tzinfo=timezone.utc)
        
        # Get candles from session start to signal time
        session_candles = candles[
            (candles["time"] >= session_start) & (candles["time"] < self._signal_time)
        ]
        
        if len(session_candles) == 0:
            return None
        
        session_open = float(session_candles.iloc[0]["open"])
        session_close = float(session_candles.iloc[-1]["close"])
        
        bias = (session_close - session_open) / self._atr_1h
        if not self._is_long:
            bias = -bias
        
        return bias
    
    def _compute_aoi_freshness(self, candles_1h: pd.DataFrame) -> dict:
        """Compute AOI interaction metrics using 1H candles.
        
        aoi_time_since_last_touch: 1H bars from last touch to retest bar
        aoi_last_reaction_strength: MFE after previous reaction (not current trade)
        
        Uses retest_time (not signal_time) as the reference point.
        """
        result = {}
        
        # Use 1H candles up to retest_time
        candles = candles_1h[candles_1h["time"] < self._retest_time].copy()
        
        if candles is None or len(candles) < 2:
            result["bars_since"] = None
            result["reaction"] = None
            return result
        
        # Find previous 1H candle that touched AOI (scanning backwards)
        last_touch_idx = None
        for i in range(len(candles) - 1, -1, -1):
            row = candles.iloc[i]
            if ((row["low"] <= self._aoi_high and row["low"] >= self._aoi_low)
              or (row["high"] <= self._aoi_high and row["high"] >= self._aoi_low)):
                last_touch_idx = i
                break
        
        if last_touch_idx is None:
            # No prior interaction
            result["bars_since"] = None
            result["reaction"] = None
            return result
        
        # aoi_time_since_last_touch = 1H bars between last touch and retest bar
        result["bars_since"] = len(candles) - 1 - last_touch_idx
        
        # Find exit candle: first 1H bar fully outside AOI after last touch
        exit_idx = None
        for i in range(last_touch_idx + 1, len(candles)):
            row = candles.iloc[i]
            if row["high"] < self._aoi_low or row["low"] > self._aoi_high:
                exit_idx = i
                break
        
        if exit_idx is None:
            result["reaction"] = None
            return result
        
        # Find next AOI touch after exit (to limit reaction window)
        next_touch_idx = None
        for i in range(exit_idx + 1, len(candles)):
            row = candles.iloc[i]
            if row["high"] >= self._aoi_low and row["low"] <= self._aoi_high:
                next_touch_idx = i
                break
        
        # Reaction window: exit_candle to next_touch or end of available candles
        reaction_end = next_touch_idx if next_touch_idx else len(candles)
        reaction_candles = candles.iloc[exit_idx:reaction_end]
        
        if len(reaction_candles) == 0:
            result["reaction"] = None
            return result
        
        exit_close = float(candles.iloc[exit_idx]["close"])
        
        if self._is_long:
            mfe = float(reaction_candles["high"].max()) - exit_close
        else:
            mfe = exit_close - float(reaction_candles["low"].min())
        
        result["reaction"] = mfe / self._atr_1h if self._atr_1h > 0 else None
        
        return result
    
    def _compute_momentum_chase(self, candles: pd.DataFrame) -> Optional[float]:
        """Compute distance from last impulse bar.
        
        Large impulse bar = candle body >= 1.5 × average body size.
        """
        if len(candles) < 10:
            return None
        
        # Compute average body size
        recent_candles = candles.tail(50)
        bodies = np.abs(recent_candles["close"].values - recent_candles["open"].values)
        avg_body = float(np.mean(bodies))
        
        if avg_body <= 0:
            return None
        
        threshold = PRE_ENTRY_V2_LARGE_BAR_MULTIPLIER * avg_body
        
        # Find last large bar aligned with direction
        for i in range(len(candles) - 1, -1, -1):
            row = candles.iloc[i]
            body = abs(row["close"] - row["open"])
            
            if body >= threshold:
                # Check if aligned with direction
                is_bullish = row["close"] > row["open"]
                if (self._is_long and is_bullish) or (not self._is_long and not is_bullish):
                    last_impulse_close = float(row["close"])
                    distance = abs(self._entry_price - last_impulse_close) / self._atr_1h
                    return distance
        
        return None
    
    def _compute_htf_range_size(self) -> dict:
        """Compute HTF range size (compressed vs expanded markets).
        
        Daily: (max(high) - min(low)) / atr over last 20 daily candles
        Weekly: (max(high) - min(low)) / atr over last 12 weekly candles
        """
        result = {}
        
        # Mid-TF range size over last 20 candles
        daily_candles = self._store.get(ACTIVE_PROFILE.trend_tf_mid).get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) >= 20:
            last_20_daily = daily_candles.tail(20)
            range_high = float(last_20_daily["high"].max())
            range_low = float(last_20_daily["low"].min())
            result["daily"] = (range_high - range_low) / self._atr_1h
        
        # High-TF range size over last 12 candles
        weekly_candles = self._store.get(ACTIVE_PROFILE.trend_tf_high).get_candles_up_to(self._signal_time)
        if weekly_candles is not None and len(weekly_candles) >= 12:
            last_12_weekly = weekly_candles.tail(12)
            range_high = float(last_12_weekly["high"].max())
            range_low = float(last_12_weekly["low"].min())
            result["weekly"] = (range_high - range_low) / self._atr_1h
        
        return result
    
    def _compute_aoi_position_in_htf_range(self) -> dict:
        """Compute AOI midpoint position inside HTF range.
        
        Position = (aoi_mid - range_low) / (range_high - range_low)
        Normalized 0–1 where 0 = edge low, 1 = edge high
        """
        result = {}
        aoi_mid = (self._aoi_low + self._aoi_high) / 2
        
        # Mid-TF range (last 20 candles)
        daily_candles = self._store.get(ACTIVE_PROFILE.trend_tf_mid).get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) >= 20:
            last_20_daily = daily_candles.tail(20)
            range_high = float(last_20_daily["high"].max())
            range_low = float(last_20_daily["low"].min())
            range_size = range_high - range_low
            if range_size > 0:
                result["daily"] = (aoi_mid - range_low) / range_size
        
        # High-TF range (last 12 candles)
        weekly_candles = self._store.get(ACTIVE_PROFILE.trend_tf_high).get_candles_up_to(self._signal_time)
        if weekly_candles is not None and len(weekly_candles) >= 12:
            last_12_weekly = weekly_candles.tail(12)
            range_high = float(last_12_weekly["high"].max())
            range_low = float(last_12_weekly["low"].min())
            range_size = range_high - range_low
            if range_size > 0:
                result["weekly"] = (aoi_mid - range_low) / range_size
        
        return result
    
    def _compute_break_impulse_range(self) -> Optional[float]:
        """Compute break candle range size in ATR units.
        
        break_impulse_range_atr = (high - low) / atr_1h
        """
        if self._break_candle is None or self._atr_1h <= 0:
            return None
        
        candle_range = self._break_candle["high"] - self._break_candle["low"]
        return candle_range / self._atr_1h
    
    def _compute_break_impulse_body(self) -> Optional[float]:
        """Compute break candle body size in ATR units.
        
        break_impulse_body_atr = abs(close - open) / atr_1h
        """
        if self._break_candle is None or self._atr_1h <= 0:
            return None
        
        body = abs(self._break_candle["close"] - self._break_candle["open"])
        return body / self._atr_1h
    
    def _compute_break_close_location(self) -> Optional[float]:
        """Compute break candle close location within its range.
        
        Measures follow-through conviction.
        For bullish: (close - low) / (high - low)
        For bearish: (high - close) / (high - low)
        """
        if self._break_candle is None:
            return None
        
        high = self._break_candle["high"]
        low = self._break_candle["low"]
        close = self._break_candle["close"]
        candle_range = high - low
        
        if candle_range <= 0:
            return None
        
        if self._is_long:
            return (close - low) / candle_range
        else:
            return (high - close) / candle_range
    
    def _compute_retest_body_penetration(self) -> Optional[float]:
        """Compute retest candle body penetration score.
        
        Combines body size relative to AOI height and penetration depth.
        retest_candle_body_penetration = penetration * 0.5 + body_aoi_ratio * 0.5
        """
        if self._retest_candle is None:
            return None
        
        aoi_height = self._aoi_high - self._aoi_low
        if aoi_height <= 0:
            return None
        
        # Body size
        body = abs(self._retest_candle["close"] - self._retest_candle["open"])
        body_aoi_ratio = body / aoi_height
        
        # Penetration depth into AOI
        high = self._retest_candle["high"]
        low = self._retest_candle["low"]
        
        if self._is_long:
            # Bullish: How far did low penetrate into AOI (below aoi_high)?
            if low >= self._aoi_high:
                penetration = 0.0  # Didn't enter AOI
            elif low <= self._aoi_low:
                penetration = 1.0  # Fully penetrated
            else:
                penetration = (self._aoi_high - low) / aoi_height
        else:
            # Bearish: How far did high penetrate into AOI (above aoi_low)?
            if high <= self._aoi_low:
                penetration = 0.0  # Didn't enter AOI
            elif high >= self._aoi_high:
                penetration = 1.0  # Fully penetrated
            else:
                penetration = (high - self._aoi_low) / aoi_height
        
        # Combined score: 50% penetration + 50% body ratio
        return penetration * 0.5 + body_aoi_ratio * 0.5

    def _compute_day_range_atr(self) -> Optional[float]:
        """Compute Daily Range Consumed Ratio (Range since 00:00 UTC / ATR)."""
        if self._atr_1h <= 0: return None
        
        # Get candles strictly before signal
        candles_1h = self._store.get_1h_candles().get_candles_up_to(self._signal_time)
        if candles_1h is None or candles_1h.empty: return None
        
        candles_past = candles_1h[candles_1h["time"] < self._signal_time]
        if candles_past.empty: return None

        # Filter from 00:00 UTC of signal day
        # Ensure we are careful about timezones, assume candles are UTC compatible
        day_start = self._signal_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # If signal time is tz-aware, make day_start tz-aware?
        # CandleStore handles normalization but here we filter DataFrame directly.
        # If candles['time'] is tz-aware, we need match.
        # Usually internal candles are naive UTC or consistent.
        if candles_past["time"].dt.tz is not None and day_start.tzinfo is None:
             # Assume day_start is UTC
             day_start = day_start.replace(tzinfo=timezone.utc)
        elif candles_past["time"].dt.tz is None and day_start.tzinfo is not None:
             day_start = day_start.replace(tzinfo=None)

        today_candles = candles_past[candles_past["time"] >= day_start]
        
        if today_candles.empty: return 0.0
        
        day_h = today_candles["high"].max()
        day_l = today_candles["low"].min()
        return (day_h - day_l) / self._atr_1h

    def _compute_opposing_wick_ratio(self) -> Optional[float]:
        """Compute wick ratio of the signal candle (last closed candle before signal)."""
        # Get candles strictly before signal
        candles_1h = self._store.get_1h_candles().get_candles_up_to(self._signal_time)
        if candles_1h is None or candles_1h.empty: return None
        
        candles_past = candles_1h[candles_1h["time"] < self._signal_time]
        if candles_past.empty: return None
        
        # Signal candle is the last closed candle
        sig_candle = candles_past.iloc[-1]
        
        c_high = sig_candle["high"]
        c_low = sig_candle["low"]
        c_close = sig_candle["close"]
        c_range = c_high - c_low
        
        if c_range <= 0: return 0.0
        
        if self._is_long:
            # Bullish: Upper wick (rejection)
            return (c_high - c_close) / c_range
        else:
            # Bearish: Lower wick (rejection)
            return (c_close - c_low) / c_range

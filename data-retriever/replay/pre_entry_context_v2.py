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
from trend.bias import calculate_trend_alignment_strength

from .config import (
    PRE_ENTRY_V2_IMPULSE_THRESHOLD_ATR,
    PRE_ENTRY_V2_LARGE_BAR_MULTIPLIER,
    PRE_ENTRY_V2_AOI_REACTION_LOOKBACK,
    PRE_ENTRY_V2_IMPULSE_LOOKBACK,
    SESSION_ASIA_START,
    SESSION_ASIA_END,
    SESSION_LONDON_START,
    SESSION_LONDON_END,
    SESSION_NY_START,
    SESSION_NY_END,
    TREND_ALIGNMENT_TIMEFRAMES,
)

if TYPE_CHECKING:
    from .candle_store import CandleStore
    from .market_state import SymbolState


@dataclass
class PreEntryContextV2Data:
    """Pre-entry market environment metrics computed at replay time."""
    
    # HTF Range Position
    htf_range_position_daily: Optional[float] = None
    htf_range_position_weekly: Optional[float] = None
    
    # Distance to HTF Boundaries
    distance_to_daily_high_atr: Optional[float] = None
    distance_to_daily_low_atr: Optional[float] = None
    distance_to_weekly_high_atr: Optional[float] = None
    distance_to_weekly_low_atr: Optional[float] = None
    distance_to_4h_high_atr: Optional[float] = None
    distance_to_4h_low_atr: Optional[float] = None
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


class PreEntryContextV2Calculator:
    """Computes pre-entry market environment metrics from candle data.
    
    All computations use candles strictly before the entry candle.
    """
    
    def __init__(
        self,
        candle_store: "CandleStore",
        signal_time: datetime,
        direction: TrendDirection,
        entry_price: float,
        atr_1h: float,
        aoi_low: float,
        aoi_high: float,
        state: "SymbolState",
    ):
        self._store = candle_store
        self._signal_time = signal_time
        self._direction = direction
        self._entry_price = entry_price
        self._atr_1h = atr_1h
        self._aoi_low = aoi_low
        self._aoi_high = aoi_high
        self._state = state
        self._is_long = direction == TrendDirection.BULLISH
    
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
        
        return PreEntryContextV2Data(
            # HTF Range Position
            htf_range_position_daily=_to_python_float(htf_range.get("daily")),
            htf_range_position_weekly=_to_python_float(htf_range.get("weekly")),
            # HTF Distances
            distance_to_daily_high_atr=_to_python_float(htf_distances.get("daily_high")),
            distance_to_daily_low_atr=_to_python_float(htf_distances.get("daily_low")),
            distance_to_weekly_high_atr=_to_python_float(htf_distances.get("weekly_high")),
            distance_to_weekly_low_atr=_to_python_float(htf_distances.get("weekly_low")),
            distance_to_4h_high_atr=_to_python_float(htf_distances.get("4h_high")),
            distance_to_4h_low_atr=_to_python_float(htf_distances.get("4h_low")),
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
        )
    
    def _compute_htf_range_positions(self) -> dict:
        """Compute position within daily and weekly ranges.
        
        Uses most recently closed daily/weekly candle.
        """
        result = {}
        
        # Get last closed daily candle
        daily_candles = self._store.get_1d_candles().get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) > 0:
            last_daily = daily_candles.iloc[-1]
            daily_high = float(last_daily["high"])
            daily_low = float(last_daily["low"])
            daily_range = daily_high - daily_low
            if daily_range > 0:
                result["daily"] = (self._entry_price - daily_low) / daily_range
        
        # Get last closed weekly candle
        weekly_candles = self._store.get_1w_candles().get_candles_up_to(self._signal_time)
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
        
        # Get last closed 4H candle
        candles_4h = self._store.get_4h_candles().get_candles_up_to(self._signal_time)
        if candles_4h is not None and len(candles_4h) > 0:
            last_4h = candles_4h.iloc[-1]
            h4_high = float(last_4h["high"])
            h4_low = float(last_4h["low"])
            
            result["4h_high"] = abs(h4_high - self._entry_price) / self._atr_1h
            result["4h_low"] = abs(self._entry_price - h4_low) / self._atr_1h
        
        # Get last closed daily candle
        daily_candles = self._store.get_1d_candles().get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) > 0:
            last_daily = daily_candles.iloc[-1]
            daily_high = float(last_daily["high"])
            daily_low = float(last_daily["low"])
            
            result["daily_high"] = abs(daily_high - self._entry_price) / self._atr_1h
            result["daily_low"] = abs(self._entry_price - daily_low) / self._atr_1h
        
        # Get last closed weekly candle
        weekly_candles = self._store.get_1w_candles().get_candles_up_to(self._signal_time)
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
        """Estimate how many bars the trend has been active.
        
        Approximation: count bars where price movement is directionally aligned.
        """
        if len(candles) < 2:
            return 0
        
        # Simple heuristic: count consecutive bars with aligned closes
        age = 0
        for i in range(len(candles) - 1, 0, -1):
            current = candles.iloc[i]
            prev = candles.iloc[i - 1]
            
            if self._is_long:
                # Long: current close >= previous close
                if current["close"] < prev["close"] * 0.998:  # Small tolerance
                    break
            else:
                # Short: current close <= previous close
                if current["close"] > prev["close"] * 1.002:
                    break
            
            age += 1
            if age >= 200:  # Cap at 200 bars
                break
        
        return age
    
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
    
    def _compute_aoi_freshness(self, candles: pd.DataFrame) -> dict:
        """Compute AOI interaction metrics.
        
        aoi_time_since_last_touch: Bars since last AOI overlap
        aoi_last_reaction_strength: MFE in ATR after last AOI exit
        """
        result = {}
        
        # Find last bar that overlapped AOI
        last_touch_idx = None
        for i in range(len(candles) - 1, -1, -1):
            row = candles.iloc[i]
            if row["high"] >= self._aoi_low and row["low"] <= self._aoi_high:
                last_touch_idx = i
                break
        
        if last_touch_idx is None:
            # No prior interaction
            result["bars_since"] = None
            result["reaction"] = None
            return result
        
        # Bars since last touch
        result["bars_since"] = len(candles) - 1 - last_touch_idx
        
        # Find the exit from AOI and compute reaction strength
        exit_idx = None
        for i in range(last_touch_idx, len(candles)):
            row = candles.iloc[i]
            if row["high"] < self._aoi_low or row["low"] > self._aoi_high:
                exit_idx = i
                break
        
        if exit_idx is None or exit_idx >= len(candles) - 1:
            result["reaction"] = None
            return result
        
        # Compute MFE after exit (looking forward, but within available candles)
        lookback_end = min(exit_idx + PRE_ENTRY_V2_AOI_REACTION_LOOKBACK, len(candles))
        post_exit_candles = candles.iloc[exit_idx:lookback_end]
        
        if len(post_exit_candles) == 0:
            result["reaction"] = None
            return result
        
        exit_close = float(candles.iloc[exit_idx]["close"])
        
        if self._is_long:
            mfe = float(post_exit_candles["high"].max()) - exit_close
        else:
            mfe = exit_close - float(post_exit_candles["low"].min())
        
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

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
    
    # HTF Range Size (compressed vs expanded markets)
    htf_range_size_daily_atr: Optional[float] = None
    htf_range_size_weekly_atr: Optional[float] = None
    
    # AOI Position Inside HTF Range
    aoi_midpoint_range_position_daily: Optional[float] = None
    aoi_midpoint_range_position_weekly: Optional[float] = None
    
    # Break Candle Metrics
    break_impulse_range_atr: Optional[float] = None      # (high - low) / atr_1h
    break_impulse_body_atr: Optional[float] = None       # abs(close - open) / atr_1h
    break_close_location: Optional[float] = None         # bullish: (close-low)/(high-low), bearish: (high-close)/(high-low)
    
    # Retest Candle Metrics
    retest_candle_body_penetration: Optional[float] = None  # combined body ratio and penetration depth


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
        retest_time: datetime,
        direction: TrendDirection,
        entry_price: float,
        atr_1h: float,
        aoi_low: float,
        aoi_high: float,
        aoi_timeframe: str,
        state: "SymbolState",
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
            # HTF Range Size
            htf_range_size_daily_atr=_to_python_float(htf_range_size.get("daily")),
            htf_range_size_weekly_atr=_to_python_float(htf_range_size.get("weekly")),
            # AOI Position in HTF Range
            aoi_midpoint_range_position_daily=_to_python_float(aoi_position.get("daily")),
            aoi_midpoint_range_position_weekly=_to_python_float(aoi_position.get("weekly")),
            # Break Candle Metrics
            break_impulse_range_atr=_to_python_float(self._compute_break_impulse_range()),
            break_impulse_body_atr=_to_python_float(self._compute_break_impulse_body()),
            break_close_location=_to_python_float(self._compute_break_close_location()),
            # Retest Candle Metrics
            retest_candle_body_penetration=_to_python_float(self._compute_retest_body_penetration()),
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
        """Estimate how many hours the trend has been fully aligned (all 3 TFs).
        
        Logic:
        1. Check if all 3 TFs (4H, 1D, 1W) are currently aligned with direction
        2. If not all aligned, return 0
        3. For each TF, find when the trend flipped to current direction (scanning backwards)
        4. Return hours from the most recent flip to signal_time
        """
        # Check if all 3 TFs are aligned
        if self._state.trend_4h != self._direction:
            return 0
        if self._state.trend_1d != self._direction:
            return 0
        if self._state.trend_1w != self._direction:
            return 0
        
        # Find when each TF trend flipped to current direction
        flip_time_4h = self._find_trend_flip_time("4H")
        flip_time_1d = self._find_trend_flip_time("1D")
        flip_time_1w = self._find_trend_flip_time("1W")
        
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
        if timeframe == "4H":
            tf_candles = self._store.get_4h_candles().get_candles_up_to(self._signal_time)
            lookback = 50  # ~8 days
        elif timeframe == "1D":
            tf_candles = self._store.get_1d_candles().get_candles_up_to(self._signal_time)
            lookback = 30  # ~1 month
        elif timeframe == "1W":
            tf_candles = self._store.get_1w_candles().get_candles_up_to(self._signal_time)
            lookback = 20  # ~5 months
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
        
        # Daily range size over last 20 candles
        daily_candles = self._store.get_1d_candles().get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) >= 20:
            last_20_daily = daily_candles.tail(20)
            range_high = float(last_20_daily["high"].max())
            range_low = float(last_20_daily["low"].min())
            result["daily"] = (range_high - range_low) / self._atr_1h
        
        # Weekly range size over last 12 candles
        weekly_candles = self._store.get_1w_candles().get_candles_up_to(self._signal_time)
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
        
        # Daily range (last 20 candles)
        daily_candles = self._store.get_1d_candles().get_candles_up_to(self._signal_time)
        if daily_candles is not None and len(daily_candles) >= 20:
            last_20_daily = daily_candles.tail(20)
            range_high = float(last_20_daily["high"].max())
            range_low = float(last_20_daily["low"].min())
            range_size = range_high - range_low
            if range_size > 0:
                result["daily"] = (aoi_mid - range_low) / range_size
        
        # Weekly range (last 12 candles)
        weekly_candles = self._store.get_1w_candles().get_candles_up_to(self._signal_time)
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

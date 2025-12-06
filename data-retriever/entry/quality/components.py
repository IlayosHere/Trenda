from __future__ import annotations

from typing import List

from .utils import (
    body_size,
    clamp,
    full_range,
    penetration_depth,
    wick_down,
    wick_into_aoi,
    wick_up,
    candle_direction_with_trend
)
from models import TrendDirection
from models.market import Candle

def compute_penetration_score(
    candles: List[Candle],
    trend: TrendDirection,
    aoi_low: float,
    aoi_high: float,
    aoi_height: float,
    retest_idx: int,
    break_idx: int,
) -> float:
    deepest = 0.0

    relevant_candles = [
        candles[i]
        for i in range(retest_idx, break_idx + 1)
        if not (candles[i].high < aoi_low or candles[i].low > aoi_high)
    ]

    for candle in relevant_candles:
        candle_range = full_range(candle)
        if trend == TrendDirection.BULLISH:
            penetration = max(0.0, aoi_high - candle.low) / aoi_height
            wick_part = wick_down(candle) / candle_range
        else:  # bearish
            penetration = max(0.0, candle.high - aoi_low) / aoi_height
            wick_part = wick_up(candle) / candle_range

        if penetration > deepest:
            deepest = penetration
            # Check if penetration is mostly wick (e.g., close barely inside AOI)
            if wick_part > 0.5:
                deepest += wick_part / 2.5 #TODO: check about the numbers

    S1 = deepest

    return clamp(S1)


def compute_wick_momentum_score(
    candles: List[Candle],
    trend: TrendDirection,
    aoi_low: float,
    aoi_high: float,
    aoi_height: float,
    break_idx: int,
    break_candle: Candle,
    after_break_candle: Candle | None,
) -> float:
    MAX_BREAK_WICK_RATIO = 0.6
    MAX_PRE_BREAK_WICK_RATIO = 0.4
    MAX_AFTER_BREAK_WICK_RATIO = 0.4
    # Break wick 
    wick_break = wick_into_aoi(break_candle, trend, aoi_low, aoi_high)
    break_wick_ratio = clamp(wick_break / aoi_height)
    break_wick_score =  min(1.0, break_wick_ratio / MAX_BREAK_WICK_RATIO)
    
    # Pre break wick
    pre_break = candles[break_idx - 1]
    wick_prev = wick_into_aoi(pre_break, trend, aoi_low, aoi_high)
    prev_wick_ratio = clamp(wick_prev / aoi_height)
    pre_break_wick_score =  min(1.0, prev_wick_ratio / MAX_PRE_BREAK_WICK_RATIO)

    # After break wick
    if after_break_candle is not None:
        wick_after = wick_into_aoi(after_break_candle, trend, aoi_low, aoi_high)
        after_wick_ratio = clamp(wick_after / aoi_height)
        after_break_wick_score =  min(1.0, after_wick_ratio / MAX_AFTER_BREAK_WICK_RATIO)
        S2 = 0.5 * break_wick_score + 0.3 * pre_break_wick_score + 0.2 * after_break_wick_score
    else:
        S2 = 0.7 * break_wick_score + 0.3 * pre_break_wick_score
        
    return clamp(S2)


def compute_breaking_candle_quality(
    break_candle: Candle,
    aoi_high: float,
    aoi_low: float,
    aoi_height: float,
    trend: TrendDirection,
) -> float:
    MAX_WICK_RATIO = 0.5
    MAX_DIST_RATIO = 0.7
    MAX_DIR_RATIO = 0.8
    MIN_SCORE_FAVOR = 0.75
    
    # 1. Wick with trend (bigger = better)
    trend_wick = (
        wick_down(break_candle)
        if trend == TrendDirection.BULLISH
        else wick_up(break_candle)
    )
    candle_range = full_range(break_candle)
    wick_ratio = trend_wick / candle_range
    wick_score = min(1.0, wick_ratio / MAX_WICK_RATIO)

    # 2. Close far away from AOI
    dist_from_aoi = (
        (break_candle.close - aoi_high)
        if trend == TrendDirection.BULLISH
        else (aoi_low - break_candle.close)
    )
    dist_ratio = clamp(dist_from_aoi / aoi_height)
    dist_score = min(1.0, dist_ratio / MAX_DIST_RATIO)

    # 3. Big candle in trend direction
    candle_body = body_size(break_candle)
    is_trend = candle_direction_with_trend(break_candle, trend) #TODO: check if always return 1
    dir_ratio = int(is_trend) * clamp(candle_body / aoi_height)
    dir_score = min(1.0, dir_ratio / MAX_DIR_RATIO)
    
    # Final Score
    if (wick_score >= MIN_SCORE_FAVOR):
         S3 = clamp(0.4 * wick_score + 0.1 * dir_score + 0.5 * dist_score)
    elif (dir_score >= MIN_SCORE_FAVOR):
         S3 = clamp(0.1 * wick_score + 0.4 * dir_score + 0.5 * dist_score)
    else:
         S3 = clamp(0.25 * wick_score + 0.25 * dir_score + 0.5 * dist_score)
    return S3


def compute_impulse_dominance_score(
    break_candle: Candle,
    retest_candle: Candle,
    after_break_candle: Candle | None,
    trend: TrendDirection,
    aoi_high: float,
    aoi_low: float,
) -> float:
    BREAK_MAX_DOMINANCE = 0.6
    AFTER_BREAK_MAX_DOMINANCE = 0.85
    CANDLES_RATIO_PENTALY = 0.7
    
    body_break = body_size(break_candle)
    body_retest = body_size(retest_candle)
    # 1) Dominance of Close Beyond Retest Open Of Breaking Candle
    if trend == TrendDirection.BULLISH:
        dist_from_aoi = break_candle.close - aoi_high
        break_candle_close_diff = break_candle.close - retest_candle.open
    else:  # bearish
        dist_from_aoi = aoi_low - break_candle.close
        break_candle_close_diff = retest_candle.open - break_candle.close

    dominance_ratio = break_candle_close_diff / dist_from_aoi
    break_dominance_score = min(1.0, dominance_ratio / BREAK_MAX_DOMINANCE)

    # 2) Dominance of Close Beyond Retest Open Of Closing Candle
    if after_break_candle:
        if trend == TrendDirection.BULLISH:
            dist_from_aoi = after_break_candle.close - aoi_high
            after_break_close_diff = after_break_candle.close - retest_candle.open
        else:  # bearish
            dist_from_aoi = aoi_low - after_break_candle.close
            after_break_close_diff = retest_candle.open - after_break_candle.close

        dominance_ratio = after_break_close_diff / dist_from_aoi
        after_break_dominance_score = min(1.0, dominance_ratio / AFTER_BREAK_MAX_DOMINANCE)

    # 3) Breaking candle body dominance ratio
    candles_ratio = body_break / body_retest
    if candles_ratio < 1:
        candles_ratio * CANDLES_RATIO_PENTALY
    dominance_ratio = min(1.0, candles_ratio)

    # Final Result
    if after_break_candle:
        S4 = clamp(0.4 * break_dominance_score + 
                   0.2 * after_break_dominance_score + 
                   0.4 * dominance_ratio)
    else:
        S4 = clamp(0.5 * break_dominance_score + 
                   0.5 * dominance_ratio)
    return S4


def compute_after_break_confirmation(
    after_break_candle: Candle | None,
    break_candle: Candle,
    trend: TrendDirection,
    aoi_low: float,
    aoi_high: float,
    aoi_height: float,
) -> float | None:
    if after_break_candle is None:
        return None
    
    MAX_DIST_RATIO = 0.8
    
    # Wick with trend
    wick_after = wick_into_aoi(after_break_candle, trend, aoi_low, aoi_high)
    wick_ratio = clamp(wick_after / aoi_height)
    
    # Big body candle
    body_break = body_size(break_candle)
    body_after = body_size(after_break_candle)
    body_ratio_score = clamp(body_after / body_break)

    # Close far away from AOI
    dist_from_aoi = (
        (after_break_candle.close - aoi_high)
        if trend == TrendDirection.BULLISH
        else (aoi_low - after_break_candle.close)
    )
    dist_ratio = clamp(dist_from_aoi / aoi_height)
    dist_score = min(1.0, dist_ratio / MAX_DIST_RATIO)
    
    trend_continuation = 1.0 if candle_direction_with_trend(after_break_candle, trend) else 0.0
    if trend_continuation == 1.0:
        S5 = clamp(0.25 * wick_ratio + 0.25 * body_ratio_score + 0.5 * dist_score)
    else:
        S5 = clamp(0.1 * wick_ratio + 0.1 * body_ratio_score + 0.3 * dist_score + 0.5 * trend_continuation)
        
    return S5

def compute_candle_count_score(retest_idx: int, break_idx: int) -> float:
    n = break_idx - retest_idx - 1
    if n == 0:
        S6 = 0.4
    elif n <= 3:
        S6 = 1.0
    elif n == 4:
        S6 = 0.8
    elif n == 5:
        S6 = 0.5
    elif n == 6:
        S6 = 0.3
    else:
        S6 = 0.25
    return clamp(S6)


def compute_retest_entry_quality(
    retest_candle: Candle,
    trend: TrendDirection,
    aoi_low: float,
    aoi_high: float,
    aoi_height: float,
) -> float:
    MAX_PENETRATION = 0.7
    MAX_WICK_RATIO = 0.3
    
    # Check Retest candle body into the AOI
    body_retest = body_size(retest_candle)
    penetration = penetration_depth(retest_candle, aoi_low, aoi_high)
    penetration_score = min(1.0, penetration / MAX_PENETRATION)
    
    body_retest_ratio = clamp(body_retest / aoi_height)
    
    # Check retest candle wick into the AOI
    wick_retest = wick_into_aoi(retest_candle, trend, aoi_low, aoi_high) / aoi_height
    w_score = min(1.0, wick_retest / MAX_WICK_RATIO)
    
    # Final Score
    return clamp(0.35 * body_retest_ratio + 0.15 * w_score + 0.5 * penetration_score)


def compute_opposing_wick_resistance(
    trend: TrendDirection, break_candle: Candle, after_break_candle: Candle | None
) -> float:
    MAX_WICK_RATIO = 0.5
    S8 = None
    
    breaking_candle_opposing_wick = (
        wick_down(break_candle)
        if trend == TrendDirection.BEARISH
        else wick_up(break_candle)
    )
    wick_ratio = breaking_candle_opposing_wick / body_size(break_candle)
    breaking_wick_score = min(1.0, wick_ratio / MAX_WICK_RATIO)
        
    if after_break_candle is None:
        S8 = 1 - breaking_wick_score
    else:
        after_candle_opposing_wick = (
            wick_down(after_break_candle)
            if trend == TrendDirection.BEARISH
            else wick_up(after_break_candle)
        )
        wick_ratio = after_candle_opposing_wick / body_size(after_break_candle)
        after_breaking_wick_score = min(1.0, wick_ratio / MAX_WICK_RATIO)
        S8 = 1 - (0.5 * breaking_wick_score + 0.5 * after_breaking_wick_score)
        
    return clamp(S8)


def calculate_final_score(
    S1: float,
    S2: float,
    S3: float,
    S4: float,
    S5: float | None,
    S6: float,
    S7: float,
    S8: float,
) -> float:
    if S5 is not None:
        score = (
                0.18 * S1
                + 0.09 * S2
                + 0.17 * S3
                + 0.10 * S4
                + 0.25 * S5
                + 0.11 * S6
                + 0.03 * S7
                + 0.07 * S8
        )
    else:
        score = (
                0.19 * S1
                + 0.10 * S2
                + 0.34 * S3
                + 0.12 * S4
                + 0.13 * S6
                + 0.04 * S7
                + 0.08 * S8
        )

    return clamp(score)

from __future__ import annotations

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


def compute_penetration_score(candles, trend: str, aoi_low: float, aoi_high: float, retest_idx: int, break_idx: int) -> float:
    aoi_height = aoi_high - aoi_low
    deepest = 0.0

    relevant_candles = [
        candles[i]
        for i in range(retest_idx, break_idx + 1)
        if not (candles[i].high < aoi_low or candles[i].low > aoi_high)
    ]

    for candle in relevant_candles:
        if trend == "bullish":
            penetration = max(0.0, aoi_high - candle.low) / aoi_height
            wick_part = (candle.close - candle.low) / (candle.high - candle.low)
        else:  # bearish
            penetration = max(0.0, candle.high - aoi_low) / aoi_height
            wick_part = (candle.high - candle.open) / (candle.high - candle.low)

        if penetration > deepest:
            deepest = penetration
            # Check if penetration is mostly wick (e.g., close barely inside AOI)
            if wick_part > 0.5:
                deepest += wick_part / 2.5

    S1 = deepest

    return clamp(S1)


def compute_wick_momentum_score(
        candles,
        trend: str,
        aoi_low: float,
        aoi_high: float,
        break_idx: int,
        after_break_idx: int | None,
        aoi_height: float,
        break_candle,
) -> float:
    wick_break = wick_into_aoi(break_candle, trend, aoi_low, aoi_high)
    break_wick_overlap = clamp(wick_break / aoi_height)

    pre_break = candles[break_idx - 1]
    wick_prev = wick_into_aoi(pre_break, trend, aoi_low, aoi_high)
    prev_wick_overlap = clamp(wick_prev / aoi_height)

    if after_break_idx is not None:
        after_break = candles[after_break_idx]
        wick_after = wick_into_aoi(after_break, trend, aoi_low, aoi_high)
        after_wick_overlap = clamp(wick_after / aoi_height)
        S2 = 0.5 * break_wick_overlap + 0.3 * prev_wick_overlap + 0.2 * after_wick_overlap
    else:
        S2 = 0.7 * break_wick_overlap + 0.3 * prev_wick_overlap
    return clamp(S2)


def compute_breaking_candle_quality(break_candle,
                                    aoi_high: float,
                                    aoi_low: float,
                                    aoi_height: float,
                                    trend: str):
    MAX_WICK_RATIO = 0.5
    MAX_DIST_RATIO = 0.7
    MAX_DIR_RATIO = 0.8
    
    # 1. Wick with trend (bigger = better)
    trend_wick = wick_down(break_candle) if trend == "bullish" else wick_up(break_candle)
    candle_range = full_range(break_candle)
    wick_ratio = trend_wick / candle_range
    wick_score = min(1.0, max(0.0, wick_ratio / MAX_WICK_RATIO))

    # 2. Close far away from AOI
    dist_from_aoi = (break_candle.close - aoi_high) if trend == "bullish" else (aoi_low - break_candle.close)
    dist_ratio = clamp(dist_from_aoi / aoi_height)
    dist_score = min(1.0, dist_ratio / MAX_DIST_RATIO)

    # 3. Big candle in trend direction
    cnalde_body = body_size(break_candle)
    is_trend = candle_direction_with_trend(break_candle, trend) #TODO: check if always return 1
    dir_ratio = int(is_trend) * clamp(cnalde_body / aoi_height)
    dir_score = min(1.0, dir_ratio / MAX_DIR_RATIO)
    
    # Final Score
    if (wick_score >= 0.8):
         S3 = clamp(0.35 * wick_score + 0.15 * dir_score + 0.5 * dist_score)
    elif (dir_score >= 0.8):
         S3 = clamp(0.15 * wick_score + 0.35 * dir_score + 0.5 * dist_score)
    else:
         S3 = clamp(0.25 * wick_score + 0.25 * dir_score + 0.5 * dist_score)
    return S3


def compute_impulse_dominance_score(break_candle, retest_candle, aoi_high: float, aoi_low: float, trend: str) -> float:
    aoi_height = aoi_high - aoi_low

    body_break = body_size(break_candle)
    body_retest = body_size(retest_candle)

    if trend == "bullish":
        close_diff = break_candle.close - retest_candle.open
        diffToCandleRatio = close_diff/body_break
    else:  # bearish
        close_diff = retest_candle.open - break_candle.close
        diffToCandleRatio = close_diff / body_retest

    if diffToCandleRatio >= 0.3:
        closeDominance = 1.0
    elif diffToCandleRatio >= 0.2:
        closeDominance = 0.7
    elif diffToCandleRatio >= 0.1:
        closeDominance = 0.3
    else:
        closeDominance = 0.0

    # 2) Body dominance ratio (R)
    if body_retest == 0:
        dominanceRatio = 1.0 if body_break > 0 else 0.0
    else:
        candlesRatio = clamp(body_break / body_retest)
        dominanceRatio = 1.0 if candlesRatio > 1.0 else 0.0

    S4 = clamp(0.5 * closeDominance + 0.5 * dominanceRatio)
    return S4


def compute_after_break_confirmation(
        candles,
        trend: str,
        aoi_low: float,
        aoi_high: float,
        after_break_idx: int | None,
        aoi_height: float,
        break_candle
):
    S5 = None
    bodyBreak = body_size(break_candle)
    if after_break_idx is not None:
        after_break = candles[after_break_idx]
        wick_after = wick_into_aoi(after_break, trend, aoi_low, aoi_high)
        wickInAOI = clamp(wick_after / aoi_height)
        body_after = body_size(after_break)
        if body_after >= bodyBreak:
            B_after = 1.0
        else:
            B_after = clamp(body_after / bodyBreak) if bodyBreak != 0 else 0.0

        isTrend = 1.0 if candle_direction_with_trend(after_break, trend) else 0.0

        S5 = clamp(0.2 * wickInAOI + 0.3 * B_after + 0.5 * isTrend)
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
        S6 = max(0.0, 1 - 0.15 * (n - 3))
    return clamp(S6)


def compute_retest_entry_quality(
        retest_candle,
        trend: str,
        aoi_low: float,
        aoi_high: float,
        aoi_height: float,
) -> float:
    bodyRetest = body_size(retest_candle)
    pen = penetration_depth(retest_candle, aoi_low, aoi_high)
    if pen >= 0.6:
        inDepth = 1.0
    elif pen >= 0.3:
        inDepth = 0.5
    else:
        return 0
    bodyRetest = clamp(bodyRetest / aoi_height)
    wick_retest = wick_into_aoi(retest_candle, trend, aoi_low, aoi_high) / (aoi_high - aoi_low)
    if wick_retest >= 0.25:
        W_penalty = 1.0
    elif wick_retest >= 0.1:
        W_penalty = 0.5
    else:
        W_penalty = 0.0
    return clamp(0.3 * bodyRetest + 0.2 * W_penalty + 0.5 * inDepth)


def compute_opposing_wick_resistance(candles, trend: str, break_idx: int, retest_idx: int,
                                     after_break_idx: int | None) -> float:
    penalties = 0
    candidates = []
    candidates.append(candles[break_idx])
    if after_break_idx is not None:
        candidates.append(candles[after_break_idx])

    for candle in candidates:
        opposing = wick_down(candle) if trend == "bearish" else wick_up(candle)
        if opposing > 0.6 * body_size(candle):
            penalties += 1

    if penalties == 0:
        S8 = 1.0
    elif penalties == 1:
        S8 = 0.5
    else:
        S8 = 0.2
    return clamp(S8)


def calculate_final_score(S1: float, S2: float, S3: float, S4: float, S5, S6: float, S7: float, S8: float) -> float:
    if S5 is not None:
        score = (
                0.13 * S1
                + 0.10 * S2
                + 0.17 * S3
                + 0.10 * S4
                + 0.25 * S5
                + 0.15 * S6
                + 0.03 * S7
                + 0.07 * S8
        )
    else:
        score = (
                0.15 * S1
                + 0.10 * S2
                + 0.33 * S3
                + 0.12 * S4
                + 0.18 * S6
                + 0.05 * S7
                + 0.07 * S8
        )

    return clamp(score)

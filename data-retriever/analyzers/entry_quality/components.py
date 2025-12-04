from __future__ import annotations

from .utils import (
    body_size,
    clamp,
    full_range,
    penetration_depth,
    wick_down,
    wick_into_aoi,
    wick_up
)

def compute_penetration_score(candles, aoi_low: float, aoi_high: float, retest_idx: int, break_idx: int) -> float:
    aoi_height = aoi_high - aoi_low
    if aoi_height <= 0:
        return 0.0

    max_penetration = 0.0
    deepest_by_wick_only = False

    for idx in range(retest_idx, break_idx + 1):
        candle = candles[idx]

        # Candle touches AOI at all?
        touches = not (candle.high < aoi_low or candle.low > aoi_high)
        if not touches:
            continue

        # Total penetration depth relative to AOI height
        pen = penetration_depth(candle, aoi_low, aoi_high)
        if pen <= 0.0:
            continue

        # Track deepest penetration
        if pen > max_penetration:
            max_penetration = pen

            # Determine if deepest penetration came from wick-only
            body_high = max(candle.open, candle.close)
            body_low = min(candle.open, candle.close)
            body_overlap = max(0.0, min(body_high, aoi_high) - max(body_low, aoi_low))
            body_penetration = body_overlap / aoi_height if aoi_height > 0 else 0.0

            deepest_by_wick_only = (body_penetration == 0.0 and pen > 0.0)

    # If nothing penetrated the AOI at all → S1 = 0
    if max_penetration == 0.0:
        return 0.0

    # Base score = depth of deepest probe
    S1 = max_penetration

    # Weak probe: no candle reached at least 30% deep
    if max_penetration < 0.3:
        S1 *= 0.4

    # Wick-only deep probe bonus
    if deepest_by_wick_only and max_penetration >= 0.3:
        S1 = 0.6 * S1 + 0.4 * max_penetration  # slight uplift

    return clamp(S1)


def compute_wick_momentum_score(
    candles,
    trend: str,
    aoi_low: float,
    aoi_high: float,
    retest_idx: int,
    break_idx: int,
    after_break_idx: int | None,
    aoi_height: float,
    break_candle,
) -> float:
    if break_idx - 1 == retest_idx:
        return 0.0

    pre_break = candles[break_idx - 1]
    wick_break = wick_into_aoi(break_candle, trend, aoi_low, aoi_high)
    W_break = clamp(wick_break / aoi_height)

    wick_prev = wick_into_aoi(pre_break, trend, aoi_low, aoi_high)
    body_prev = body_size(pre_break)
    W_prev = 1.0 if wick_prev >= body_prev else 0.0

    if after_break_idx is not None:
        after_break = candles[after_break_idx]
        wick_after = wick_into_aoi(after_break, trend, aoi_low, aoi_high)
        body_after = body_size(after_break)
        W_after = 1.0 if wick_after >= body_after else 0.0
        S2 = 0.5 * W_break + 0.3 * W_prev + 0.2 * W_after
    else:
        S2 = 0.7 * W_break + 0.3 * W_prev
    return clamp(S2)

def compute_breaking_candle_quality(break_candle, 
                                    retest_candle, 
                                    aoi_high: float,
                                    aoi_low: float,
                                    aoi_height: float, 
                                    trend: str):
    boundary = aoi_high if trend == "bullish" else aoi_low
    distance_raw = break_candle.close - boundary if trend == "bullish" else boundary - break_candle.close
    D = clamp(distance_raw / aoi_height)

    body_break = body_size(break_candle)
    body_retest = body_size(retest_candle)
    E = clamp(body_break / body_retest) if body_retest != 0 else 0.0

    opposing_wick = wick_down(break_candle) if trend == "bearish" else wick_up(break_candle)
    if opposing_wick <= 0.2 * body_break:
        W_opp = 1.0
    elif opposing_wick <= 0.5 * body_break:
        W_opp = 0.5
    else:
        W_opp = 0.0

    B = clamp(body_break / full_range(break_candle)) if full_range(break_candle) != 0 else 0.0
    S3 = clamp(0.4 * D + 0.25 * E + 0.2 * W_opp + 0.15 * B)
    return S3, body_break, body_retest

def compute_impulse_dominance_score(break_candle, retest_candle, aoi_high: float, aoi_low: float, trend: str) -> float:
    aoi_height = aoi_high - aoi_low
    body_break = body_size(break_candle)
    body_retest = body_size(retest_candle)

    # 1) Continuous close dominance (C)
    if trend == "bullish":
        close_diff = break_candle.close - retest_candle.open
    else:  # bearish
        close_diff = retest_candle.open - break_candle.close

    if close_diff <= 0:
        C = 0.0
    else:
        C = clamp(close_diff / aoi_height)

    # 2) Body dominance ratio (R)
    if body_retest != 0:
        R = clamp(body_break / body_retest)
    else:
        # If retest body is 0 (doji-like), treat any non-zero break body as strong
        R = 1.0 if body_break > 0 else 0.0

    S4 = clamp(0.5 * C + 0.5 * R)
    return S4

def compute_after_break_confirmation(
    candles,
    trend: str,
    aoi_low: float,
    aoi_high: float,
    after_break_idx: int | None,
    body_break: float,
    aoi_height: float,
):
    S5 = None
    if after_break_idx is not None:
        after_break = candles[after_break_idx]
        wick_after = wick_into_aoi(after_break, trend, aoi_low, aoi_high)
        W = clamp(wick_after / aoi_height)

        body_after = body_size(after_break)
        if body_after >= body_break:
            B_after = 1.0
        else:
            B_after = clamp(body_after / body_break) if body_break != 0 else 0.0

        S5 = clamp(0.6 * W + 0.4 * B_after)
    return S5


def compute_candle_count_score(retest_idx: int, break_idx: int) -> float:
    n = break_idx - retest_idx - 1
    if n == 0:
        S6 = 0.4
    elif n <= 2:
        S6 = 1.0
    elif n == 3:
        S6 = 0.9
    elif n == 4:
        S6 = 0.7
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
    body_retest: float,
    aoi_height: float,
) -> float:
    B_retest = clamp(body_retest / aoi_height)
    wick_retest = wick_into_aoi(retest_candle, trend, aoi_low, aoi_high)
    if wick_retest <= 0.3 * body_retest:
        W_penalty = 1.0
    elif wick_retest <= body_retest:
        W_penalty = 0.5
    else:
        W_penalty = 0.0
    return clamp(0.7 * B_retest + 0.3 * W_penalty)


def compute_opposing_wick_resistance(candles, trend: str, break_idx: int, retest_idx: int, after_break_idx: int | None) -> float:
    penalties = 0
    candidates = []
    if break_idx - 1 != retest_idx:
        candidates.append(candles[break_idx - 1])
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

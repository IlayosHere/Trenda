from __future__ import annotations

from typing import Iterable


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` between ``low`` and ``high``."""

    return max(low, min(high, value))


def body_size(candle) -> float:
    """Return the absolute body size of a candle."""

    return abs(candle.close - candle.open)


def full_range(candle) -> float:
    """Return the full high-to-low range of a candle."""

    return candle.high - candle.low


def wick_up(candle) -> float:
    """Return the size of the upper wick."""

    return candle.high - max(candle.open, candle.close)


def wick_down(candle) -> float:
    """Return the size of the lower wick."""

    return min(candle.open, candle.close) - candle.low


def wick_in_direction_of_trend(candle, trend: str) -> float:
    """Return the wick that aligns with the given trend direction."""

    return wick_down(candle) if trend == "bullish" else wick_up(candle)


def wick_into_aoi(candle, trend: str, aoi_low: float, aoi_high: float) -> float:
    """Compute how much of the wick (excluding body) overlaps the AOI."""

    if trend == "bullish":
        wick_start, wick_end = candle.low, min(candle.open, candle.close)
    else:
        wick_start, wick_end = max(candle.open, candle.close), candle.high

    overlap_start = max(wick_start, aoi_low)
    overlap_end = min(wick_end, aoi_high)
    overlap = max(0.0, overlap_end - overlap_start)
    return overlap


def penetration_depth(candle, aoi_low: float, aoi_high: float) -> float:
    """Return the AOI penetration depth normalized by the AOI height."""

    aoi_height = aoi_high - aoi_low
    if aoi_height <= 0:
        return 0.0

    overlap_start = max(candle.low, aoi_low)
    overlap_end = min(candle.high, aoi_high)
    overlap = max(0.0, overlap_end - overlap_start)
    return overlap / aoi_height


def _is_close_inside_aoi(candle, aoi_low: float, aoi_high: float) -> bool:
    return aoi_low <= candle.close <= aoi_high


def _average(values: Iterable[float]) -> float:
    total = 0.0
    count = 0
    for value in values:
        total += value
        count += 1
    return total / count if count else 0.0


def evaluate_entry_quality(
    candles: list,
    aoi_low: float,
    aoi_high: float,
    trend: str,
    retest_idx: int,
    break_idx: int,
    after_break_idx: int | None,
) -> float:
    aoi_height = aoi_high - aoi_low
    if aoi_height <= 0:
        return 0.0

    retest_candle = candles[retest_idx]
    break_candle = candles[break_idx]

    # S1 — Deep Penetration Into AOI
    penetration_ratios = []
    for idx in range(retest_idx, break_idx + 1):
        candle = candles[idx]
        if _is_close_inside_aoi(candle, aoi_low, aoi_high):
            penetration = penetration_depth(candle, aoi_low, aoi_high)
            penetration_ratio = penetration / aoi_height
            penetration_ratios.append(penetration_ratio)

    S1 = _average(penetration_ratios)
    if all(ratio < 0.3 for ratio in penetration_ratios):
        S1 *= 0.4
    S1 = clamp(S1)

    # S2 — Wick Momentum Into AOI (Shift / Rejection Clues)
    if break_idx - 1 == retest_idx:
        S2 = 0.0
    else:
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
        S2 = clamp(S2)

    # S3 — Breaking Candle Quality
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

    # S4 — Impulse Dominance vs Retest
    if trend == "bullish":
        C = 1.0 if break_candle.close > retest_candle.open else 0.0
    else:
        C = 1.0 if break_candle.close < retest_candle.open else 0.0
    R = clamp(body_break / body_retest) if body_retest != 0 else 0.0
    S4 = clamp(0.5 * C + 0.5 * R)

    # S5 — After-Break Confirmation (Only if after_break_idx exists)
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

    # S6 — Candle Count (Decisiveness)
    n = break_idx - retest_idx
    if n <= 3:
        S6 = 1.0
    elif n == 4:
        S6 = 0.75
    elif n == 5:
        S6 = 0.5
    elif n == 6:
        S6 = 0.3
    else:
        S6 = max(0.0, 1 - 0.15 * (n - 3))
    S6 = clamp(S6)

    # S7 — Retest Entry Candle Quality (Initial Touch Body)
    B_retest = clamp(body_retest / aoi_height)
    wick_retest = wick_into_aoi(retest_candle, trend, aoi_low, aoi_high)
    if wick_retest <= 0.3 * body_retest:
        W_penalty = 1.0
    elif wick_retest <= body_retest:
        W_penalty = 0.5
    else:
        W_penalty = 0.0
    S7 = clamp(0.7 * B_retest + 0.3 * W_penalty)

    # S8 — Opposing Wick Resistance (3-Candle Check)
    penalties = 0
    candidates = []
    if break_idx - 1 != retest_idx:
        candidates.append(candles[break_idx - 1])
    candidates.append(break_candle)
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
    S8 = clamp(S8)

    # FINAL WEIGHTS
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

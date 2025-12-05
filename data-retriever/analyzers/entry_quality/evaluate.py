from __future__ import annotations

from .components import (
    calculate_final_score,
    compute_after_break_confirmation,
    compute_breaking_candle_quality,
    compute_candle_count_score,
    compute_impulse_dominance_score,
    compute_opposing_wick_resistance,
    compute_penetration_score,
    compute_retest_entry_quality,
    compute_wick_momentum_score,
)


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
    after_break_candle = None
    if after_break_idx:
        after_break_candle = candles[after_break_idx]

    S1 = compute_penetration_score(candles,
                                   trend,
                                   aoi_low,
                                   aoi_high,
                                   aoi_height,
                                   retest_idx,
                                   break_idx)

    S2 = compute_wick_momentum_score(candles,
                                     trend,
                                     aoi_low,
                                     aoi_high,
                                     aoi_height,
                                     break_idx,
                                     break_candle,
                                     after_break_candle)

    S3 = compute_breaking_candle_quality(break_candle,
                                         aoi_high,
                                         aoi_low,
                                         aoi_height,
                                         trend)

    S4 = compute_impulse_dominance_score(break_candle,
                                         retest_candle,
                                         after_break_candle,
                                         trend)

    S5 = compute_after_break_confirmation(after_break_candle,
                                          break_candle,
                                          trend,
                                          aoi_low,
                                          aoi_high,
                                          aoi_height)
    
    S6 = compute_candle_count_score(retest_idx, break_idx)

    S7 = compute_retest_entry_quality(retest_candle,
                                      trend,
                                      aoi_low,
                                      aoi_high,
                                      aoi_height)

    S8 = compute_opposing_wick_resistance(trend, break_candle, after_break_candle)

    return calculate_final_score(S1, S2, S3, S4, S5, S6, S7, S8)

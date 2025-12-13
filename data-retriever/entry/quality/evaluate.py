from __future__ import annotations

from typing import List

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
from .score_models import QualityResult
from models import TrendDirection
from models.market import Candle


def evaluate_entry_quality(
    candles: List[Candle],
    aoi_low: float,
    aoi_high: float,
    trend: TrendDirection,
    retest_idx: int,
    break_idx: int,
    after_break_idx: int | None,
) -> QualityResult:
    def _empty_result() -> QualityResult:
        """Return an empty quality result for invalid inputs."""
        return QualityResult(final_score=0.0, tier="NONE", stage_scores=[])
    
    trend_direction = TrendDirection.from_raw(trend)
    if trend_direction is None:
        return _empty_result()
    aoi_height = aoi_high - aoi_low
    if aoi_height <= 0:
        return _empty_result()
    
    relevant_candles = [
        candles[i]
        for i in range(retest_idx, break_idx + 1)
        if not (candles[i].high < aoi_low or candles[i].low > aoi_high)
    ]
    
    if len(relevant_candles) == 0:
        return _empty_result()

    retest_candle = candles[retest_idx]
    break_candle = candles[break_idx]
    after_break_candle = None
    if after_break_idx is not None:
        after_break_candle = candles[after_break_idx]

    S1 = compute_penetration_score(candles,
                                   trend_direction,
                                   aoi_low,
                                   aoi_high,
                                   aoi_height)

    S2 = compute_wick_momentum_score(candles,
                                     trend_direction,
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
                                         trend_direction)

    S4 = compute_impulse_dominance_score(break_candle,
                                         retest_candle,
                                         after_break_candle,
                                         trend_direction,
                                         aoi_high,
                                         aoi_low)

    S5 = compute_after_break_confirmation(after_break_candle,
                                          break_candle,
                                          trend_direction,
                                          aoi_low,
                                          aoi_high,
                                          aoi_height)
    
    S6 = compute_candle_count_score(retest_idx, break_idx)

    S7 = compute_retest_entry_quality(retest_candle,
                                      trend_direction,
                                      aoi_low,
                                      aoi_high,
                                      aoi_height)

    S8 = compute_opposing_wick_resistance(trend_direction, break_candle, after_break_candle)

    return calculate_final_score(S1, S2, S3, S4, S5, S6, S7, S8)

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import find_peaks

# Import all constants and type definitions
from constants import (
    BREAK_BEARISH,
    BREAK_BULLISH,
    NO_BREAK,
    SWING_HIGH,
    SWING_LOW,
    SwingPoint,
    TREND_BEARISH,
    TREND_BULLISH,
    TREND_NEUTRAL,
)
from models import TrendDirection

def get_swing_points(
    prices: np.ndarray, distance: int, prominence: float
) -> List[SwingPoint]:
    """
    Finds all significant swing highs ('H') and lows ('L') from a price array.
    """
    high_indices, _ = find_peaks(prices, distance=distance, prominence=prominence)
    low_indices, _ = find_peaks(-prices, distance=distance, prominence=prominence)

    swings: List[SwingPoint] = []
    for idx in high_indices:
        swings.append(
            SwingPoint(index=int(idx), price=float(prices[idx]), kind=SWING_HIGH)
        )
    for idx in low_indices:
        swings.append(
            SwingPoint(index=int(idx), price=float(prices[idx]), kind=SWING_LOW)
        )

    swings.sort(key=lambda x: x.index)  # Sort by index (chronologically)
    swings.append(find_last_point(prices, swings[-1]))
    return swings


#TODO: check the relavance of this function rn after we work with finished candles only
def find_last_point(prices: np.ndarray, last_swing_point: SwingPoint) -> SwingPoint:
    if last_swing_point.kind == SWING_LOW:
        return SwingPoint(last_swing_point.index + 1, float(prices[-1]), SWING_HIGH)
    else:
        return SwingPoint(last_swing_point.index + 1, float(prices[-1]), SWING_LOW)

def _find_initial_structure(
    all_swings: List[SwingPoint],
) -> Tuple[Optional[SwingPoint], Optional[SwingPoint]]:
    """
    Finds the first chronological High and Low to establish the initial structure.
    """
    initial_high: Optional[SwingPoint] = None
    initial_low: Optional[SwingPoint] = None

    for swing in all_swings:
        swing_type = swing.kind
        if swing_type == SWING_HIGH and initial_high is None:
            initial_high = swing
        elif swing_type == SWING_LOW and initial_low is None:
            initial_low = swing
        if initial_high and initial_low:
            break

    return initial_high, initial_low


def _check_for_structure_break(
    current_swing: SwingPoint, struct_high: SwingPoint, struct_low: SwingPoint
) -> str:
    """
    Checks if a new swing has broken the established market structure.
    """
    price = current_swing.price
    swing_type = current_swing.kind

    if swing_type == SWING_HIGH and price > struct_high.price:
        return BREAK_BULLISH
    elif swing_type == SWING_LOW and price < struct_low.price:
        return BREAK_BEARISH
    return NO_BREAK


def _find_corresponding_structural_swing(
    break_type: str, new_swing_index: int, all_swings: List[SwingPoint]
) -> Optional[SwingPoint]:
    """
    After a break, searches backwards to find the corresponding
    structural point (e.g., the new Higher Low or Lower High).
    """
    # If bullish break, we are looking for the last 'L' (Higher Low)
    search_for_type = SWING_LOW if break_type == BREAK_BULLISH else SWING_HIGH

    for j in range(new_swing_index - 1, -1, -1):
        if all_swings[j].kind == search_for_type:
            return all_swings[j]

    return None  # Fallback


@dataclass(frozen=True)
class TrendAnalysisResult:
    """Container for trend analysis outcomes."""

    trend: Optional[TrendDirection]
    structural_high: Optional[SwingPoint]
    structural_low: Optional[SwingPoint]


def analyze_snake_trend(
    all_swings: List[SwingPoint],
) -> TrendAnalysisResult:
    """
    Orchestrates the analysis of swings to find the trend and structural points.
    """
    if len(all_swings) < 2:
        return TrendAnalysisResult(TREND_NEUTRAL, None, None)

    initial_high, initial_low = _find_initial_structure(all_swings)

    if not initial_high or not initial_low:
        return TrendAnalysisResult(TREND_NEUTRAL, None, None)

    current_trend: TrendDirection = TREND_NEUTRAL
    current_structure: Dict[str, SwingPoint] = {
        SWING_HIGH: initial_high,
        SWING_LOW: initial_low,
    }

    for i in range(len(all_swings)):
        current_swing = all_swings[i]

        break_type = _check_for_structure_break(
            current_swing, current_structure[SWING_HIGH], current_structure[SWING_LOW]
        )

        if break_type == BREAK_BULLISH:
            current_trend = TREND_BULLISH
            new_low = _find_corresponding_structural_swing(BREAK_BULLISH, i, all_swings)
            current_structure[SWING_HIGH] = current_swing
            if new_low:
                current_structure[SWING_LOW] = new_low

        elif break_type == BREAK_BEARISH:
            current_trend = TREND_BEARISH
            new_high = _find_corresponding_structural_swing(
                BREAK_BEARISH, i, all_swings
            )
            current_structure[SWING_LOW] = current_swing
            if new_high:
                current_structure[SWING_HIGH] = new_high

    return TrendAnalysisResult(
        current_trend,
        current_structure[SWING_HIGH],
        current_structure[SWING_LOW],
    )

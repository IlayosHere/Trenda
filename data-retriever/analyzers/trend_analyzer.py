import numpy as np
from scipy.signal import find_peaks
from externals.data_fetcher import fetch_data
from typing import List, Dict, Tuple, Optional

# Import all constants and type definitions
from constants import (
    SwingPoint,
    TREND_BULLISH,
    TREND_BEARISH,
    TREND_NEUTRAL,
    BREAK_BULLISH,
    BREAK_BEARISH,
    NO_BREAK,
)

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
        swings.append((int(idx), prices[idx], "H"))
    for idx in low_indices:
        swings.append((int(idx), prices[idx], "L"))

    swings.sort(key=lambda x: x[0])  # Sort by index (chronologically)
    swings.append(find_last_point(prices, swings[-1]))
    return swings


def find_last_point(prices: np.ndarray, last_swing_point: SwingPoint) -> SwingPoint:
    if last_swing_point[2] == "L":
        return (last_swing_point[0] + 1, prices[-1], "H")
    else:
        return (last_swing_point[0] + 1, prices[-1], "L")

def _find_initial_structure(
    all_swings: List[SwingPoint],
) -> Tuple[Optional[SwingPoint], Optional[SwingPoint]]:
    """
    Finds the first chronological High and Low to establish the initial structure.
    """
    initial_high: Optional[SwingPoint] = None
    initial_low: Optional[SwingPoint] = None

    for swing in all_swings:
        swing_type = swing[2]
        if swing_type == "H" and initial_high is None:
            initial_high = swing
        elif swing_type == "L" and initial_low is None:
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
    price = current_swing[1]
    swing_type = current_swing[2]

    if swing_type == "H" and price > struct_high[1]:
        return BREAK_BULLISH
    elif swing_type == "L" and price < struct_low[1]:
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
    search_for_type = "L" if break_type == BREAK_BULLISH else "H"

    for j in range(new_swing_index - 1, -1, -1):
        if all_swings[j][2] == search_for_type:
            return all_swings[j]

    return None  # Fallback


def analyze_snake_trend(
    all_swings: List[SwingPoint],
) -> Tuple[str, Optional[SwingPoint], Optional[SwingPoint]]:
    """
    Orchestrates the analysis of swings to find the trend and structural points.
    """
    if len(all_swings) < 2:
        return TREND_NEUTRAL, None, None

    initial_high, initial_low = _find_initial_structure(all_swings)

    if not initial_high or not initial_low:
        return TREND_NEUTRAL, None, None

    current_trend: str = TREND_NEUTRAL
    current_structure: Dict[str, SwingPoint] = {"H": initial_high, "L": initial_low}

    for i in range(len(all_swings)):
        current_swing = all_swings[i]

        break_type = _check_for_structure_break(
            current_swing, current_structure["H"], current_structure["L"]
        )

        if break_type == BREAK_BULLISH:
            current_trend = TREND_BULLISH
            new_low = _find_corresponding_structural_swing(BREAK_BULLISH, i, all_swings)
            current_structure["H"] = current_swing
            if new_low:
                current_structure["L"] = new_low

        elif break_type == BREAK_BEARISH:
            current_trend = TREND_BEARISH
            new_high = _find_corresponding_structural_swing(
                BREAK_BEARISH, i, all_swings
            )
            current_structure["L"] = current_swing
            if new_high:
                current_structure["H"] = new_high

    return current_trend, current_structure["H"], current_structure["L"]

#new branch
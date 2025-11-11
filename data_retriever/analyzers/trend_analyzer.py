"""Utilities for identifying market structure trends from swing points."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import find_peaks

from data_retriever.constants import (
    BREAK_BEARISH,
    BREAK_BULLISH,
    NO_BREAK,
    SwingPoint,
    TREND_BEARISH,
    TREND_BULLISH,
    TREND_NEUTRAL,
)


def get_swing_points(prices: np.ndarray, distance: int, prominence: float) -> List[SwingPoint]:
    """Identify swing highs/lows from a price series."""
    high_indices, _ = find_peaks(prices, distance=distance, prominence=prominence)
    low_indices, _ = find_peaks(-prices, distance=distance, prominence=prominence)

    swings: List[SwingPoint] = []
    for idx in high_indices:
        swings.append((int(idx), float(prices[idx]), "H"))
    for idx in low_indices:
        swings.append((int(idx), float(prices[idx]), "L"))

    if not swings:
        return []

    swings.sort(key=lambda swing: swing[0])
    swings.append(_infer_last_point(prices, swings[-1]))
    return swings


def _infer_last_point(prices: np.ndarray, last_swing_point: SwingPoint) -> SwingPoint:
    next_index = last_swing_point[0] + 1
    next_price = float(prices[-1])
    next_label = "H" if last_swing_point[2] == "L" else "L"
    return next_index, next_price, next_label


def analyze_snake_trend(all_swings: List[SwingPoint]) -> Tuple[str, Optional[SwingPoint], Optional[SwingPoint]]:
    """Derive the prevailing trend and current structural highs/lows."""
    if len(all_swings) < 2:
        return TREND_NEUTRAL, None, None

    initial_high, initial_low = _find_initial_structure(all_swings)
    if not initial_high or not initial_low:
        return TREND_NEUTRAL, None, None

    current_trend = TREND_NEUTRAL
    current_structure: Dict[str, SwingPoint] = {"H": initial_high, "L": initial_low}

    for index, current_swing in enumerate(all_swings):
        break_type = _check_for_structure_break(
            current_swing, current_structure["H"], current_structure["L"]
        )

        if break_type == BREAK_BULLISH:
            current_trend = TREND_BULLISH
            current_structure["H"] = current_swing
            new_low = _find_corresponding_structural_swing(BREAK_BULLISH, index, all_swings)
            if new_low:
                current_structure["L"] = new_low
        elif break_type == BREAK_BEARISH:
            current_trend = TREND_BEARISH
            current_structure["L"] = current_swing
            new_high = _find_corresponding_structural_swing(BREAK_BEARISH, index, all_swings)
            if new_high:
                current_structure["H"] = new_high

    return current_trend, current_structure["H"], current_structure["L"]


def _find_initial_structure(
    all_swings: List[SwingPoint],
) -> Tuple[Optional[SwingPoint], Optional[SwingPoint]]:
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
    price = current_swing[1]
    swing_type = current_swing[2]

    if swing_type == "H" and price > struct_high[1]:
        return BREAK_BULLISH
    if swing_type == "L" and price < struct_low[1]:
        return BREAK_BEARISH
    return NO_BREAK


def _find_corresponding_structural_swing(
    break_type: str, new_swing_index: int, all_swings: List[SwingPoint]
) -> Optional[SwingPoint]:
    search_for_type = "L" if break_type == BREAK_BULLISH else "H"

    for idx in range(new_swing_index - 1, -1, -1):
        if all_swings[idx][2] == search_for_type:
            return all_swings[idx]
    return None

"""Swing extraction helpers for AOI analysis."""

from typing import List
import numpy as np

from data_retriever.analyzers.trend_analyzer import get_swing_points

from .models import AOIContext


def extract_swings(prices: np.ndarray, context: AOIContext) -> List:
    """Detect swing highs/lows using configured prominence and distance."""
    params = context.params
    return get_swing_points(prices, params["distance"], params["prominence"])


__all__ = ["extract_swings"]

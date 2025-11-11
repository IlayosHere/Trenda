"""Directional weighting and classification for AOI zones."""

from typing import Dict, List

from .config import AOI_ALIGNMENT_WEIGHT


def apply_directional_weighting(
    zones: List[Dict[str, float]],
    current_price: float,
    trend_direction: str,
) -> List[Dict[str, float]]:
    """Apply trend-aware weighting and label AOIs as tradable or reference."""
    results: List[Dict[str, float]] = []
    for zone in zones:
        lower = zone["lower_bound"]
        upper = zone["upper_bound"]
        zone_above_price = lower > current_price
        zone_below_price = upper < current_price

        if trend_direction == "bearish":
            is_tradable = zone_above_price
        elif trend_direction == "bullish":
            is_tradable = zone_below_price
        else:
            is_tradable = False

        weighted_score = zone["score"] * (AOI_ALIGNMENT_WEIGHT if is_tradable else 1.0)

        results.append(
            {
                "lower_bound": float(lower),
                "upper_bound": float(upper),
                "score": float(weighted_score),
                "touches": int(zone["touches"]),
                "last_swing_idx": int(zone["last_swing_idx"]),
                "type": "tradable" if is_tradable else "reference",
            }
        )
    return results


__all__ = ["apply_directional_weighting"]

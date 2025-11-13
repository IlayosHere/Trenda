from typing import Dict, List

from .context import AOIContext


def apply_directional_weighting_and_classify(
    zones: List[Dict[str, float]],
    current_price: float,
    last_bar_idx: int,
    trend_direction: str,
    context: AOIContext,
) -> List[Dict[str, float]]:
    """
    Apply direction-aware weighting to base score:
      - Bearish → AOIs ABOVE price are 'tradable' (sell), BELOW are 'reference'
      - Bullish → AOIs BELOW price are 'tradable' (buy), ABOVE are 'reference'
    """

    out: List[Dict[str, float]] = []
    for z in zones:
        lower, upper = z["lower_bound"], z["upper_bound"]
        zone_above_price = lower > current_price
        zone_below_price = upper < current_price

        if trend_direction == "bearish":
            is_tradable = zone_above_price
        elif trend_direction == "bullish":
            is_tradable = zone_below_price
        else:
            is_tradable = False

        weighted_score = z["score"] * (
            context.settings.alignment_weight if is_tradable else 1.0
        )

        out.append(
            {
                "lower_bound": float(lower),
                "upper_bound": float(upper),
                "score": float(weighted_score),
                "touches": int(z["touches"]),
                "last_swing_idx": int(z["last_swing_idx"]),
                "type": "tradable" if is_tradable else "reference",
            }
        )
    return out

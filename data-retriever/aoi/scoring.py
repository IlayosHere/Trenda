from dataclasses import replace
from typing import List

from .context import AOIContext
from models import AOIZone, TrendDirection


def apply_directional_weighting_and_classify(
    zones: List[AOIZone],
    current_price: float,
    trend_direction: TrendDirection | str,
    context: AOIContext,
) -> List[AOIZone]:
    """
    Apply direction-aware weighting to base score:
      - Bearish → AOIs ABOVE price are 'tradable' (sell), BELOW are 'reference'
      - Bullish → AOIs BELOW price are 'tradable' (buy), ABOVE are 'reference'
    """

    direction = TrendDirection.from_raw(trend_direction)
    out: List[AOIZone] = []
    for z in zones:
        lower, upper = z.lower, z.upper
        zone_above_price = upper > current_price
        zone_below_price = lower < current_price

        if direction == TrendDirection.BEARISH:
            is_tradable = zone_above_price
        elif direction == TrendDirection.BULLISH:
            is_tradable = zone_below_price
        else:
            is_tradable = False

        alignment_weight = context.settings.alignment_weight if is_tradable else 1.0
        base_score = z.score or 0.0
        weighted_score = float(base_score * alignment_weight)

        out.append(
            replace(
                z,
                score=weighted_score,
                classification="tradable" if is_tradable else "reference",
            )
        )
    return out

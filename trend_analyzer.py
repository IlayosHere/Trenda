from scipy.signal import find_peaks
from typing import List, Dict, Tuple, Optional, Any

SwingPoint = tuple[int, float, str] 
# (index, price, 'H'/'L')

TREND_BULLISH: str = "bullish"
TREND_BEARISH: str = "bearish"
TREND_NEUTRAL: str = "neutral"

# Constants for break types
BREAK_BULLISH: str = "BULLISH_BREAK"
BREAK_BEARISH: str = "BEARISH_BREAK"
NO_BREAK: str = "NO_BREAK"

def get_swing_points(prices, distance, prominence):
    high_points, _ = find_peaks(prices, distance=distance, prominence=prominence)
    low_points, _ = find_peaks(-prices, distance=distance, prominence=prominence)
    swings = []
    for idx in high_points:
        swings.append((idx, prices[idx], 'H'))
    for idx in low_points:
        swings.append((idx, prices[idx], 'L'))
        
    # 4. Sort all swings by their index (i.e., by time)
    # This gives us the chronological "snake-line"
    swings.sort(key=lambda x: x[0])
    
    return swings

def _find_initial_structure(all_swings: list[SwingPoint]):
    initial_high = None
    initial_low = None
    
    for swing in all_swings:
        swing_type = swing[2]
        if swing_type == 'H' and initial_high is None:
            initial_high = swing
        elif swing_type == 'L' and initial_low is None:
            initial_low = swing
        if initial_high and initial_low:
            break
            
    return initial_high, initial_low

def _check_for_structure_break(
    current_swing: SwingPoint, 
    struct_high: SwingPoint, 
    struct_low: SwingPoint
) -> str:
    price = current_swing[1]
    swing_type = current_swing[2]
    
    if swing_type == 'H' and price > struct_high[1]:
        return BREAK_BULLISH
        
    elif swing_type == 'L' and price < struct_low[1]:
        return BREAK_BEARISH
        
    return NO_BREAK

def _find_swing_breaking_points(
    break_type: str, 
    new_swing_index: int, 
    all_swings: list[SwingPoint]
):
    search_for_type = 'L' if break_type == BREAK_BULLISH else 'H'
    
    # Search backwards from the swing *before* the breaking one
    for j in range(new_swing_index - 1, -1, -1):
        if all_swings[j][2] == search_for_type:
            return all_swings[j] # Found it
            
    return None # Should be rare, but possible

def analyze_snake_trend(all_swings: list[SwingPoint]) -> tuple[str, SwingPoint, SwingPoint]:
    if len(all_swings) < 2:
        return TREND_NEUTRAL, None, None # Not enough data

    initial_high, initial_low = _find_initial_structure(all_swings)
    
    if not initial_high or not initial_low:
        return TREND_NEUTRAL, None, None # Failed to find initial H/L pair

    current_trend: str = TREND_NEUTRAL
    current_structure: dict[str, SwingPoint] = {"H": initial_high, "L": initial_low}

    for i in range(len(all_swings)):
        current_swing = all_swings[i]
        
        break_type = _check_for_structure_break(
            current_swing, 
            current_structure["H"], 
            current_structure["L"]
        )

        if break_type == BREAK_BULLISH:
            current_trend = TREND_BULLISH
            # Find the Higher Low (HL) that formed before this new HH
            new_low = _find_swing_breaking_points(BREAK_BULLISH, i, all_swings)
            current_structure["H"] = current_swing
            if new_low:
                current_structure["L"] = new_low
                
        elif break_type == BREAK_BEARISH:
            current_trend = TREND_BEARISH
            # Find the Lower High (LH) that formed before this new LL
            new_high = _find_swing_breaking_points(BREAK_BEARISH, i, all_swings)
            current_structure["L"] = current_swing
            if new_high:
                current_structure["H"] = new_high

    return current_trend, current_structure["H"], current_structure["L"]
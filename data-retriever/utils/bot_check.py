import pandas as pd
from entry.quality import evaluate_entry_quality
from configuration import FOREX_PAIRS, TIMEFRAMES, require_analysis_params
from externals.data_fetcher import fetch_data
from models import TrendDirection
from utils.candles import dataframe_to_candles
from logger import get_logger

logger = get_logger(__name__)

def run_bot_check(timeframe: str) -> None:
    for symbol in FOREX_PAIRS:
        run_symbol(timeframe, symbol)
         
def run_symbol(timeframe: str, symbol: str) -> None:
    formatted_timeframe = TIMEFRAMES[timeframe]
    analysis_params = require_analysis_params(timeframe)
    data = fetch_data(
        symbol,
        formatted_timeframe,
        analysis_params.lookback,
        timeframe_label=timeframe,
    )
    indexed_data = index_dataframes(data)
    #Date format: 
    # EURUSD: 2025-11-27 01:00:00 2025-11-18 15:00:00 2025-11-12 07:00:00 
    # USDJPY: 2025-11-14 14:00:00 2025-11-13 17:00:00 2025-12-01 14:00:00
    # AUDUSD: 2025-10-13 16:00:00 2025-12-02 11:00:00 
    # NZDUSD: 2025-11-03 04:00:00 
    # AUDJPY: 2025-11-28 14:00:00 
    # EURAUD: 2025-12-05 13:00:00
    # GBPNZD: 2025-12-05 13:00:00 2025-12-04 07:00:00
    # GBPAUD: 2025-12-10 09:00:00
    time = "2025-12-10 23:00:00+00:00"
    last_index = find_candles_by_time(indexed_data, time)
    logger.debug(f"Last index found: {last_index}")
    last_index_id = last_index["id"].values[0]
    count = 7 # remember to change
    nums = list(range(last_index_id, last_index_id + count))
    selected_data = select_candles(indexed_data, nums)
    # EURUSD: bearish
    # USDJPY: bullish
    # AUDUSD: bullish bearish
    # NZDUSD: bearish
    # AUDJPY: bullish
    # EURAUD: bearish
    # GBPNZD: bearish
    trend = TrendDirection.BULLISH
    # EURUSD: 1.16095 1.15893 
    # USDJPY: 154.392 154.954
    # AUDUSD: 0.65246 0.65519
    # NZDUSD: 0.5751
    # AUDJPY: 100.896
    # ERUAUD: 1.76025
    # GBPNZD: 2.31449
    aoi_high = 155.918
    # EURUSD: 1.15965 1.15758  
    # USDJPY: 153.874 154.697
    # AUDUSD: 0.65133 0.65411
    # NZDUSD: 0.57187
    # AUDJPY: 100.691
    # ERUAUD: 1.7564
    # GBPNZD: 2.311
    aoi_low = 155.694
    # prompt = build_full_prompt(symbol, selected_data, trend, aoi_high, aoi_low)
    # logger.info(prompt)

    evaluate_selected_entry(selected_data, trend, aoi_low, aoi_high)


def evaluate_selected_entry(
    selected_candles_df: pd.DataFrame,
    trend: str,
    aoi_low: float,
    aoi_high: float,
) -> float:
    candles = dataframe_to_candles(selected_candles_df)
    # Retest candle is always the first provided candle.
    retest_idx = 0
    break_idx, after_break_idx = _prompt_for_break_indices(len(candles))

    score = evaluate_entry_quality(
        candles,
        aoi_low=aoi_low,
        aoi_high=aoi_high,
        trend=trend,
        retest_idx=retest_idx,
        break_idx=break_idx,
        after_break_idx=after_break_idx,
    )

    logger.info(f"Entry quality score: {score:.4f}")
    return score
    
def find_candles_by_time(df: pd.DataFrame, time_value, time_col="time"):
    # Ensure the column exists
    if time_col not in df.columns:
        raise KeyError(f"Column '{time_col}' not found. Available: {list(df.columns)}")
    # Make a copy to avoid modifying original
    df = df.copy()
    # Convert column to datetime
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    # Convert search value to datetime
    target_time = pd.to_datetime(time_value)
    # Return the matching rows
    return df[df[time_col] == target_time]
    
def select_candles(indexed_dataframes, candle_ids, id_col="id"):
    # If only one DataFrame was passed, convert it into a list
    if isinstance(indexed_dataframes, pd.DataFrame):
        indexed_dataframes = [indexed_dataframes]

    # Combine all DataFrames
    full_df = pd.concat(indexed_dataframes, ignore_index=True)

    # Filter by the id column
    selected = full_df[full_df[id_col].isin(candle_ids)].copy()

    # Keep the original order of candle_ids if possible
    selected = (
        selected.set_index(id_col)
        .loc[candle_ids]
        .reset_index()
    )

    return selected

    
def index_dataframes(dataframes):
    dataframes = dataframes.reset_index().rename(columns={"index": "id"})
    return dataframes


def _prompt_for_break_indices(candle_count: int) -> tuple[int, int | None]:
    if candle_count == 0:
        raise ValueError("No candles provided for evaluation.")
    if candle_count == 1:
        raise ValueError("At least two candles are required to determine break and confirmation indices.")

    last_is_break = input("Is the last candle the break candle? (yes/no): ").strip().lower()
    if last_is_break in {"yes", "y"}:
        return candle_count - 1, None

    return candle_count - 2, candle_count - 1

def build_full_prompt(symbol, selected_candles_df, trend, aoi_high, aoi_low):
    # Build candle lines
    # selected_candles_df = selected_candles_df.iloc[::-1]
    candle_lines = []
    for _, row in selected_candles_df.iterrows():
        candle_lines.append(
            f'{{"Open": {row["open"]}, "high": {row["high"]}, "Low": {row["low"]}, "Close": {row["close"]}}}'
        )
    candles_text = ",\n".join(candle_lines)

    # Full final prompt (exactly as you wrote it)
    output_text = f"""
You are a senior price action analyst at a professional forex trading firm. Your evaluation directly affects real capital allocation, so your analysis must be strict, objective, rule-based, and consistent with zero randomness.
The analysis must never reinterpret candle intent (buyers/sellers). All evaluations must be based strictly on numerical geometry only.
For every candle, body and wick sizes must be calculated first before making any judgment.
Analyze ONLY the data and ONLY the rules provided below. No assumptions. No creativity. No external knowledge.

RULESET FOR AOI REJECTION EVALUATION

1. Trend determines expected rejection direction
* If the trend is bullish, the AOI is a demand zone. Price should dip into the zone and then reject upward (buy bias).
* If the trend is bearish, the AOI is a supply zone. Price should rise into the zone and then reject downward (sell bias).
Rejection must always align with the given trend.

2. Zone rules
You are given the AOI boundaries: high_end and low_end.
Valid rejection requires that at least one candle in the sequence enters the zone (touches or penetrates it).
Penetration deeper into the zone increases potential rejection strength, but deep penetration alone does NOT signal quality.
Penetration less than 25% of all candles of the zone height is considered weak, , meaning that if at least one candle penetrated more than 25% of the area, this increases confidence, even if it surpasses the zone in a bit but if not, it shows wakness.

3. Candle geometry definitions
For every candle:
* body_size = abs(close - open)
* upper_wick = high - max(open, close)
* lower_wick = min(open, close) - low
A wick is “significantly larger than the body” if wick_size >= 1.3 * body_size.
For bearish trend: the relevant wick is the UPPER wick.
For bullish trend: the relevant wick is the LOWER wick.

4. Candle sequence rules (candles are in chronological order)
You receive all candles from the retest candle - the first candle entering the AOI, up to the breaking candle or the confirmation candle after the break.

Evaluate:

A. Retest Quality
* Deeper wick penetration into the AOI increases rejection potential.
* Wick reaching at least the 25% zone depth increases confidence.
* Very deep retests require stronger momentum to confirm the trend shift. If deep retest is followed by weak break, lower the score.

B. Momentum Shift (general)
The move OUT of the zone must show clear trend-aligned momentum.
The move OUT of the zone should be stronger than the move INTO the zone.

C. Break Confirmation (close relative to the AOI)
If breaking candle (the candle that starts the move away from the zone in the trend direction) meets this condition, confidence increases:
Bullish: breaking_candle_close >= AOI_high_end * 1.0006
Bearish: breaking_candle_close <= AOI_low_end * 0.9994
* The break cannot be marginal. It must show clear distance beyond the AOI.
* Break candle must be strong: either a strong directional wick or engulfing, or a momentum-driven body.  
* Weak breaks should reduce the score.

D. Confirmation Candle After Break
If the last candle is AFTER the breaking candle:
* It must close significantly outside the AOI:
  - Bullish: breaking_candle_close >= AOI high_end * 1.0007
  - Bearish: breaking_candle_close <= AOI low_end * 0.9993
* The confirmation candle must show at least one of:
  1. Momentum continuation (strong body in trend direction)
  2. Wick retest into the AOI followed by rejection in trend direction
  3. Combination of strong break + wick confirmation candle
* If breaking candle is weak OR confirmation candle is weak, reduce the score.

5. Scoring rules (0 to 1)
Output a single score reflecting the strength of executing an order after the last candle closes:
0.0–0.2: no rejection or unclear
0.2–0.4: weak rejection
0.4–0.6: moderate or borderline
0.6–0.8: good quality rejection
0.8–1.0: strong, clean, trend-aligned rejection with clear momentum shift

The score must be strict, deterministic, and repeatable. Same input must always produce the same output.  

OUTPUT RULE
Output ONLY the final score as a number between 0 and 1. No explanations.

DATA FORMAT (structure you will receive)
Trend: <bullish|bearish>

AOI:
  high_end: <number>
  low_end: <number>

Candles:
  - open: <number>
    high: <number>
    low: <number>
    close: <number>
  - open: <number>
    high: <number>
    low: <number>
    close: <number>
  ...
(all candles from retest to break/confirmation)

When you receive data in this structure, follow ALL rules and output only the rejection score (0 to 1).   


DATA:
TREND: {trend}
AOI: {{ "high_end": {aoi_high}, "low_end": {aoi_low} }}
CANDLES: [
{candles_text}
]
"""

    return output_text.strip()

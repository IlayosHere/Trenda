import pandas as pd
from externals.data_fetcher import fetch_data
from configuration import ANALYSIS_PARAMS, TIMEFRAMES, FOREX_PAIRS

def run_bot_check(timeframe: str) -> None:
    for symbol in FOREX_PAIRS:
        run_symbol(timeframe, symbol)
         
def run_symbol(timeframe: str, symbol: str) -> None:
    formmated_timeframe = TIMEFRAMES[timeframe]
    analysis_params = ANALYSIS_PARAMS[timeframe]
    data = fetch_data(
    symbol, formmated_timeframe, analysis_params["lookback"])
    indexed_data = index_dataframes(data)
    time = input("Enter the time of the price: ")
    #Date format: EURUSD: 2025-11-19 15:00:00 
    # USDJPY: 2025-11-13 17:00:00 
    last_index = find_candles_by_time(indexed_data, time)
    print(last_index)
    nums = list(map(int, input("Enter numbers separated by space: ").split()))
    selected_data = select_candles(indexed_data, nums)
    # EURUSD: bearish USDJPY: bullish
    trend = input("enter the trend: ")
    # EURUSD: 1.15997 USDJPY: 154.392
    aoi_high = float(input("Enter the aoi high: "))
    # EURUSD: 1.15829 USDJPY: 153.874
    aoi_low = float(input("Enter the aoi low: "))
    prompt = build_full_prompt(selected_data, trend, aoi_high, aoi_low)
    print(prompt)
    
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

def build_full_prompt(selected_candles_df, trend, aoi_high, aoi_low):
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
ROLE:
You are an institutional-grade forex market-structure analyst. Your task is to evaluate whether the current market conditions provide a valid entry strictly in the direction of the given trend.

OBJECTIVE:
Return a single deterministic probability value between 0 and 1 (no text, no labels, no explanation) representing whether the current candle provides a valid entry in the direction of the trend.

DETERMINISM REQUIREMENT:
Your evaluation must be fully deterministic.
Given identical input, you must always return the exact same numerical output with no randomness.

ALLOWED INFORMATION:

Only the data provided in this prompt (TREND, AOI, CANDLES).

No indicators.

No invented data or assumptions.

INPUT FORMAT:
TREND: “Bullish” or “Bearish”
AOI: {{ "high_end": number, "low_end": number }}
CANDLES: array of candles ordered from the first candle that retested the AOI to the most recent candle.
Each candle: {{ "Open": number, "High": number, "Low": number, "Close": number }}

EVALUATION RULES:
Evaluate the full structure from the AOI retest to the current candle using deterministic logic:

The output may never be 1.0 unless ALL structural criteria score at their maximum

Confirm price interacted with the AOI.

Confirm whether the candles after the AOI show continuation, rejection, or invalidation in the direction of the trend.

Assess current candle behavior relative to structure.

Convert your structural evaluation into a probability score between 0 and 1 using a consistent, deterministic method.

OUTPUT FORMAT:
Output only one number between 0 and 1 with no additional text, no formatting, no labels.

DATA:

TREND: {trend}
AOI: {{ "high_end": {aoi_high}, "low_end": {aoi_low} }}
CANDLES: [
{candles_text}
]
"""

    return output_text.strip()

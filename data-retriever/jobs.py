from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed


from aoi import analyze_single_symbol_aoi
from configuration import (
    FOREX_PAIRS,
    TIMEFRAMES,
    require_analysis_params,
    require_aoi_lookback,
)
from logger import get_logger

logger = get_logger(__name__)
from externals.data_fetcher import fetch_data
from trend import analyze_single_symbol_trend


def _process_symbol_pipeline(
    symbol: str, 
    timeframe: str, 
    lookback: int, 
    include_aoi: bool,
    broker_timeframe: str,
    trend_lookback: int,
    aoi_lookback: int | None
) -> None:
    """Fetch and analyze data for a single symbol in its own thread."""
    try:
        # 1. Fetch
        data = fetch_data(
            symbol,
            broker_timeframe,
            lookback,
            timeframe_label=timeframe,
        )
       
        if data is None or data.empty:
            logger.error(f"  ❌ No data for {symbol} ({timeframe})")
            return

        # 2. Slice Data & Run Trend Analysis
        trend_data = data.tail(trend_lookback)
        analyze_single_symbol_trend(symbol, timeframe, trend_data)

        # 3. Slice Data & Run AOI Analysis (if requested)
        if include_aoi and aoi_lookback:
            # AOI usually needs a different lookback or the same, but we slice explicitly
            # to match original logic where we had specific subsets.
            aoi_data = data.tail(aoi_lookback)
            analyze_single_symbol_aoi(symbol, timeframe, aoi_data)

    except Exception as exc:
        logger.error(f"  ❌ Critical error processing {symbol}: {exc}")


def run_timeframe_job(timeframe: str, *, include_aoi: bool) -> None:
    """Run parallel fetch & analysis for all symbols.
    
    Each symbol is processed in its own thread to ensure isolation and 
    prevent a single failure from halting the entire job.
    """
    
    logger.info(f"\n--- 🔄 Starting Parallel Job: {timeframe} ---")
    
    broker_timeframe = TIMEFRAMES.get(timeframe)
    if broker_timeframe is None:
        logger.error(f"Unknown timeframe {timeframe}")
        return

    logger.info(f"--- 🔄 Running {timeframe} timeframe job ---")
    analysis_params = require_analysis_params(timeframe)
    trend_lookback = analysis_params.lookback
    aoi_lookback = require_aoi_lookback(timeframe) if include_aoi else None
    
    # Calculate the max lookback needed to satisfy both analyses
    fetch_lookback = max(trend_lookback, aoi_lookback or 0)

    # Parallel Execution
    workers = len(FOREX_PAIRS)
    logger.info(f"  -> Dispatching {workers} threads for {timeframe} job...")
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _process_symbol_pipeline, 
                symbol=symbol, 
                timeframe=timeframe, 
                lookback=fetch_lookback, 
                include_aoi=include_aoi, 
                broker_timeframe=broker_timeframe,
                trend_lookback=trend_lookback,
                aoi_lookback=aoi_lookback
            ): symbol
            for symbol in FOREX_PAIRS
        }
        
        for future in as_completed(futures):
            # We iterate to ensure we catch any silent thread crashes if they escape the inner try/except
            try:
                future.result()
            except Exception as e:
                symbol = futures.get(future, "Unknown")
                logger.error(f"Thread for {symbol} crashed: {e}")

    logger.info(f"--- ✅ Parallel Job {timeframe} Complete ---\n")

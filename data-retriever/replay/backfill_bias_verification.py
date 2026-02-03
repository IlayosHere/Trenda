"""Backfill script to verify existing signals against unbiased trend/AOI data.

This script takes signals from the database (where sl_model_version = 'LAST')
and recomputes the trend and AOI data using the fixed (bias-free) candle 
alignment logic. It then updates the signals with:
- real_trend_4h, real_trend_1d, real_trend_1w: Unbiased trends
- real_trend_alignment: Unbiased alignment strength
- aoi_still_valid: Whether the AOI is still generated without bias
- trend_matches_original: Whether all trends match the original

Usage:
    python replay/backfill_bias_verification.py --start 2025-01-01 --end 2025-12-31
    python replay/backfill_bias_verification.py --start 2025-06-01  # End defaults to now
"""

import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Add parent directory to path so we can import from data-retriever
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from replay.candle_store import load_symbol_candles
from replay.market_state import MarketStateManager
from replay.timeframe_alignment import TimeframeAligner
from replay.config import SCHEMA_NAME
from models import TrendDirection
from logger import get_logger

# Load environment variables first
from core import env  # noqa: F401

logger = get_logger(__name__)

# =============================================================================
# Database Configuration - UPDATE THIS URL
# =============================================================================
DATABASE_URL = "postgresql://postgres:heblish123@localhost:5432/trenda"

# =============================================================================
# Queries
# =============================================================================

FETCH_SIGNALS_FOR_BACKFILL = f"""
    SELECT id, symbol, signal_time, direction,
           trend_4h, trend_1d, trend_1w,
           aoi_timeframe, aoi_low, aoi_high, entry_price, atr_1h
    FROM {SCHEMA_NAME}.entry_signal
    WHERE sl_model_version = 'LAST'
      AND real_trend_4h IS NULL
      AND signal_time >= :start_time
      AND signal_time <= :end_time
    ORDER BY symbol, signal_time
"""

UPDATE_SIGNAL_BIAS_VERIFICATION = f"""
    UPDATE {SCHEMA_NAME}.entry_signal
    SET real_trend_4h = :real_trend_4h,
        real_trend_1d = :real_trend_1d,
        real_trend_1w = :real_trend_1w,
        real_trend_alignment = :real_trend_alignment,
        aoi_still_valid = :aoi_still_valid,
        trend_matches_original = :trend_matches_original
    WHERE id = :id
"""


def create_db_engine() -> Engine:
    """Create SQLAlchemy engine."""
    return create_engine(DATABASE_URL)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Backfill bias verification for existing signals"
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date (ISO format, default: now)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of signals per batch (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    return parser.parse_args()


def parse_datetime(date_str: str) -> datetime:
    """Parse datetime string with timezone."""
    if "T" in date_str:
        dt = datetime.fromisoformat(date_str)
    else:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_signals(engine: Engine, start_time: datetime, end_time: datetime) -> List[dict]:
    """Fetch signals that need backfill."""
    with engine.connect() as conn:
        result = conn.execute(
            text(FETCH_SIGNALS_FOR_BACKFILL),
            {"start_time": start_time, "end_time": end_time}
        )
        rows = result.fetchall()
    
    signals = []
    for row in rows:
        signals.append({
            "id": row[0],
            "symbol": row[1],
            "signal_time": row[2],
            "direction": row[3],
            "trend_4h": row[4],
            "trend_1d": row[5],
            "trend_1w": row[6],
            "aoi_timeframe": row[7],
            "aoi_low": float(row[8]) if row[8] else None,
            "aoi_high": float(row[9]) if row[9] else None,
            "entry_price": float(row[10]) if row[10] else None,
            "atr_1h": float(row[11]) if row[11] else None,
        })
    return signals


def group_signals_by_symbol(signals: List[dict]) -> dict:
    """Group signals by symbol for efficient candle loading."""
    grouped = {}
    for sig in signals:
        symbol = sig["symbol"]
        if symbol not in grouped:
            grouped[symbol] = []
        grouped[symbol].append(sig)
    return grouped


def compute_real_trends(
    signal: dict,
    state_manager: MarketStateManager,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    """Compute unbiased trends for a signal."""
    signal_time = signal["signal_time"]
    
    # Make sure signal_time is timezone-aware
    if signal_time.tzinfo is None:
        signal_time = signal_time.replace(tzinfo=timezone.utc)
    
    # Update state to signal time (this uses the fixed get_candles_up_to)
    state_manager.update_state(signal_time)
    state = state_manager.state
    
    # Get trend values
    trend_4h = state.trend_4h.value if state.trend_4h else "neutral"
    trend_1d = state.trend_1d.value if state.trend_1d else "neutral"
    trend_1w = state.trend_1w.value if state.trend_1w else "neutral"
    
    # Compute alignment
    direction = signal["direction"]
    if direction == "bullish":
        trend_dir = TrendDirection.BULLISH
    elif direction == "bearish":
        trend_dir = TrendDirection.BEARISH
    else:
        trend_dir = None
    
    alignment = state.get_trend_alignment_strength(trend_dir) if trend_dir else 0
    
    return trend_4h, trend_1d, trend_1w, alignment


def check_aoi_still_valid(
    signal: dict,
    state: "SymbolState",
) -> bool:
    """Check if the original AOI is still in the unbiased AOI list."""
    aoi_low = signal.get("aoi_low")
    aoi_high = signal.get("aoi_high")
    aoi_timeframe = signal.get("aoi_timeframe")
    
    if aoi_low is None or aoi_high is None:
        return False
    
    # Get AOIs from unbiased state
    if aoi_timeframe == "4H":
        aois = state.aois_4h
    elif aoi_timeframe == "1D":
        aois = state.aois_1d
    else:
        return False
    
    # Check if any AOI matches (with small tolerance for floating point)
    tolerance = 0.0001
    for aoi in aois:
        if (abs(aoi.lower - aoi_low) < tolerance and 
            abs(aoi.upper - aoi_high) < tolerance):
            return True
    
    return False


def check_trends_match(
    signal: dict,
    real_trend_4h: str,
    real_trend_1d: str,
    real_trend_1w: str,
) -> bool:
    """Check if all real trends match original trends."""
    return (
        signal.get("trend_4h") == real_trend_4h and
        signal.get("trend_1d") == real_trend_1d and
        signal.get("trend_1w") == real_trend_1w
    )


def process_symbol_signals(
    engine: Engine,
    symbol: str,
    signals: List[dict],
    dry_run: bool = False,
) -> Tuple[int, int, int]:
    """Process all signals for a symbol.
    
    Returns:
        Tuple of (processed, trend_matches, aoi_valid)
    """
    if not signals:
        return 0, 0, 0
    
    # Find time range for this symbol's signals
    signal_times = [s["signal_time"] for s in signals]
    min_time = min(signal_times)
    max_time = max(signal_times)
    
    # Add buffer for lookback
    start_date = min_time - timedelta(days=30)
    end_date = max_time + timedelta(days=5)
    
    # Load candles (once per symbol)
    logger.info(f"  Loading candles for {symbol}...")
    try:
        candle_store = load_symbol_candles(symbol, start_date, end_date)
    except Exception as e:
        logger.error(f"  Failed to load candles for {symbol}: {e}")
        return 0, 0, 0
    
    # Create state manager
    aligner = TimeframeAligner(candle_store)
    state_manager = MarketStateManager(symbol, candle_store, aligner)
    
    processed = 0
    trend_matches = 0
    aoi_valid = 0
    
    for sig in signals:
        try:
            # Reset state for each signal
            state_manager.reset()
            
            # Compute real trends
            real_4h, real_1d, real_1w, alignment = compute_real_trends(
                sig, state_manager
            )
            
            # Check AOI validity
            aoi_still_valid = check_aoi_still_valid(sig, state_manager.state)
            
            # Check trend match
            trends_match = check_trends_match(sig, real_4h, real_1d, real_1w)
            
            if trends_match:
                trend_matches += 1
            if aoi_still_valid:
                aoi_valid += 1
            
            if dry_run:
                logger.info(
                    f"    [DRY-RUN] Signal {sig['id']}: "
                    f"trends_match={trends_match}, aoi_valid={aoi_still_valid}"
                )
            else:
                # Update database
                with engine.connect() as conn:
                    conn.execute(
                        text(UPDATE_SIGNAL_BIAS_VERIFICATION),
                        {
                            "real_trend_4h": real_4h,
                            "real_trend_1d": real_1d,
                            "real_trend_1w": real_1w,
                            "real_trend_alignment": alignment,
                            "aoi_still_valid": aoi_still_valid,
                            "trend_matches_original": trends_match,
                            "id": sig["id"],
                        }
                    )
                    conn.commit()
            
            processed += 1
            
        except Exception as e:
            logger.error(f"    Error processing signal {sig['id']}: {e}")
    
    return processed, trend_matches, aoi_valid


def main():
    """Main entry point."""
    args = parse_args()
    
    # Parse dates
    start_time = parse_datetime(args.start)
    if args.end:
        end_time = parse_datetime(args.end)
    else:
        end_time = datetime.now(timezone.utc)
    
    logger.info("=" * 60)
    logger.info("BIAS VERIFICATION BACKFILL")
    logger.info("=" * 60)
    logger.info(f"  Start: {start_time}")
    logger.info(f"  End: {end_time}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info("=" * 60)
    
    # Create database engine
    engine = create_db_engine()
    
    # Fetch signals
    logger.info("Fetching signals...")
    signals = fetch_signals(engine, start_time, end_time)
    logger.info(f"Found {len(signals)} signals to process")
    
    if not signals:
        logger.info("No signals to process. Done.")
        return
    
    # Group by symbol
    grouped = group_signals_by_symbol(signals)
    logger.info(f"Signals span {len(grouped)} symbols")
    
    # Process each symbol
    total_processed = 0
    total_trend_matches = 0
    total_aoi_valid = 0
    
    for symbol, symbol_signals in grouped.items():
        logger.info(f"\nProcessing {symbol} ({len(symbol_signals)} signals)...")
        processed, matches, valid = process_symbol_signals(
            engine, symbol, symbol_signals, args.dry_run
        )
        total_processed += processed
        total_trend_matches += matches
        total_aoi_valid += valid
        logger.info(
            f"  ✅ {processed} processed, "
            f"{matches} trend matches, {valid} AOI valid"
        )
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total processed: {total_processed}")
    logger.info(f"  Trend matches: {total_trend_matches} ({100*total_trend_matches/max(1,total_processed):.1f}%)")
    logger.info(f"  AOI valid: {total_aoi_valid} ({100*total_aoi_valid/max(1,total_processed):.1f}%)")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

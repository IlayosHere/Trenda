"""
Backfill aoi_touch_count_since_creation for entry_signal rows.

Every signal was stored with aoi_touch_count_since_creation=0 (skipped for
performance during replay). This script recomputes the correct value using the
same swing-based touch counting as the AOI pipeline:

1. Detect swing highs/lows on the AOI's timeframe candles (via find_peaks).
2. Keep swings whose close price falls within [aoi_low, aoi_high].
4. Count valid touches = swing pairs spaced >= min_swing_gap_bars apart.

Groups signals by (symbol, aoi_timeframe) to minimise MT5 API calls —
candles are fetched once per group, covering all signals in it.

Usage:
    cd data-retriever && python replay/backfill_aoi_touch_count.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from aoi.aoi_configuration import AOI_CONFIGS
from aoi.pipeline import calculate_valid_touches
from configuration import require_analysis_params
from database.executor import DBExecutor
from externals.data_fetcher import fetch_data
from replay.config import MT5_INTERVALS, SCHEMA_NAME
from trend.structure import get_swing_points
from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Per-TF fetch lookback — large enough to cover the full replay span (~2019–2024)
# plus the per-signal aoi_lookback window. Used only for the MT5 range fetch.
# The actual swing-detection window per signal is params.aoi_lookback (or lookback).
TF_FETCH_LOOKBACK: dict[str, int] = {
    "1H": 6000,   # ~250 trading days
    "4H": 8000,   # ~5.5 years of 4H bars
    "1D": 2000,   # ~8 years of 1D bars
    "1W": 500,    # ~10 years of 1W bars
}

FETCH_SIGNALS_SQL = f"""
    SELECT
        es.id,
        es.symbol,
        es.signal_time,
        es.aoi_low,
        es.aoi_high,
        es.aoi_timeframe
    FROM {SCHEMA_NAME}.entry_signal es
    WHERE es.sl_model_version = 'CHECK_GEO'
      AND es.is_break_candle_last = TRUE
      {{signal_filter}}
    ORDER BY es.symbol, es.aoi_timeframe, es.signal_time ASC
"""

UPDATE_SQL = f"""
    UPDATE {SCHEMA_NAME}.entry_signal
    SET aoi_touch_count_since_creation = %s
    WHERE id = %s
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class SignalRow:
    signal_id: int
    symbol: str
    signal_time: datetime
    aoi_low: float
    aoi_high: float
    aoi_timeframe: str


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def fetch_signals(signal_id: int | None = None) -> list[SignalRow]:
    signal_filter = f"AND es.id = {signal_id}" if signal_id is not None else ""
    sql = FETCH_SIGNALS_SQL.format(signal_filter=signal_filter)
    rows = DBExecutor.fetch_all(sql, context="backfill_aoi_fetch")
    if not rows:
        return []

    result: list[SignalRow] = []
    for row in rows:
        signal_id, symbol, signal_time_db, aoi_low, aoi_high, aoi_timeframe = row

        if not aoi_timeframe:
            logger.warning("Signal %d has no aoi_timeframe — skipping", signal_id)
            continue

        if signal_time_db.tzinfo is None:
            signal_time_utc = signal_time_db.replace(tzinfo=timezone.utc)
        else:
            signal_time_utc = signal_time_db.astimezone(timezone.utc)

        result.append(SignalRow(
            signal_id=signal_id,
            symbol=symbol,
            signal_time=signal_time_utc,
            aoi_low=float(aoi_low),
            aoi_high=float(aoi_high),
            aoi_timeframe=aoi_timeframe,
        ))

    return result


def batch_update(updates: list[tuple[int, int]]) -> None:
    if not updates:
        return
    # params order must match UPDATE_SQL: (%s count, %s id)
    params = [(count, signal_id) for signal_id, count in updates]
    DBExecutor.execute_many(UPDATE_SQL, params, context="backfill_aoi_update")


# ---------------------------------------------------------------------------
# Touch count computation
# ---------------------------------------------------------------------------
def count_aoi_touches(
    candles: pd.DataFrame,
    aoi_low: float,
    aoi_high: float,
    signal_time: datetime,
    aoi_timeframe: str,
) -> int:
    """Count significant AOI touches using the same swing-based logic as the pipeline.

    Swing detection uses close prices (same as real AOI pipeline).
    Zone touch is checked via candle HIGH/LOW at each swing position — close prices
    at swing peaks often miss the zone even when the wick clearly touched it.
    Window = aoi_lookback (or lookback) bars before signal_time, matching the replay.
    """
    settings = AOI_CONFIGS.get(aoi_timeframe)
    if settings is None:
        return 0

    before = candles[candles["time"] < signal_time]
    if len(before) < 3:
        return 0

    params = require_analysis_params(aoi_timeframe)
    window = params.aoi_lookback or params.lookback
    before = before.tail(window).reset_index(drop=True)

    prices = np.asarray(before["close"].values, dtype=float)

    try:
        swings = get_swing_points(prices, params.distance, params.prominence)
    except Exception:
        return 0

    touching = []
    for s in swings:
        if s.index >= len(before):
            continue
        row = before.iloc[s.index]
        if row["high"] >= aoi_low and row["low"] <= aoi_high:
            touching.append(s)

    if not touching:
        return 0

    indexes = sorted(s.index for s in touching)
    return calculate_valid_touches(indexes, settings.min_swing_gap_bars)


# ---------------------------------------------------------------------------
# Per-signal processing
# ---------------------------------------------------------------------------
def process_signal(s: SignalRow) -> tuple[int, int] | None:
    """Fetch candles and compute touch count for a single signal.

    Returns (signal_id, touch_count) or None if candles unavailable.
    Each signal fetches its own window ending at signal_time, ensuring
    early signals get the full lookback regardless of other signals.
    """
    mt5_tf = MT5_INTERVALS.get(s.aoi_timeframe)
    if mt5_tf is None:
        logger.warning("Unknown aoi_timeframe '%s' for signal %d", s.aoi_timeframe, s.signal_id)
        return None

    fetch_lookback = TF_FETCH_LOOKBACK.get(s.aoi_timeframe, 6000)
    end_date = s.signal_time + timedelta(hours=2)

    candles = fetch_data(s.symbol, mt5_tf, lookback=fetch_lookback, end_date=end_date)
    if candles is None or candles.empty:
        logger.warning("No candles for signal %d (%s/%s)", s.signal_id, s.symbol, s.aoi_timeframe)
        return None

    candles["time"] = pd.to_datetime(candles["time"], utc=True)
    candles = candles.sort_values("time").reset_index(drop=True)

    touch_count = count_aoi_touches(candles, s.aoi_low, s.aoi_high, s.signal_time, s.aoi_timeframe)
    return (s.signal_id, touch_count)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def backfill_aoi_touch_count(signal_id: int | None = None) -> None:
    logger.info("Fetching signals from DB...")
    signals = fetch_signals(signal_id=signal_id)
    if not signals:
        logger.error("No signals found — check DB connection and filters")
        return

    total_signals = len(signals)
    logger.info("Found %d signals to process", total_signals)

    all_updates: list[tuple[int, int]] = []
    skipped = 0

    for i, s in enumerate(signals, start=1):
        if i % 50 == 0 or i == 1:
            logger.info("[%d/%d] processing...  (%.1f%%)", i, total_signals, i / total_signals * 100)
        result = process_signal(s)
        if result is None:
            skipped += 1
        else:
            all_updates.append(result)

    logger.info(
        "Processed: %d updated, %d skipped (no candles/unknown TF)",
        len(all_updates), skipped,
    )
    logger.info("Writing %d updates to DB...", len(all_updates))
    batch_update(all_updates)
    logger.info(
        "Done. Updated %d / %d signals (%.1f%%).",
        len(all_updates), total_signals, len(all_updates) / total_signals * 100,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill aoi_touch_count_since_creation")
    parser.add_argument(
        "--signal-id",
        type=int,
        default=None,
        help="Test on a single signal ID before running the full backfill",
    )
    args = parser.parse_args()
    backfill_aoi_touch_count(signal_id=args.signal_id)

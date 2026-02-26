"""
backfill_delayed_entry.py — Simulate delayed entry at bar 3 / bar 6.

For each qualifying signal, if price moved favorably by delay_bars after
entry, simulate a new trade entered at that bar's close with SL placed
relative to the delay bar's candle structure or the original AOI geometry.
Forward scan uses per-bar high/low — SL hits are accurate (no approximation).

Only entered observations (delay_return_atr > 0) are written.

Run year-by-year:
    cd data-retriever && python replay/backfill_delayed_entry.py --year 2019
    cd data-retriever && python replay/backfill_delayed_entry.py --year 2020
    ...

Test on a single signal first:
    cd data-retriever && python replay/backfill_delayed_entry.py --signal-id 12345
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from database.executor import DBExecutor
from externals.data_fetcher import fetch_data
from models import TrendDirection
from replay.config import SCHEMA_NAME
from logger import get_logger

logger = get_logger(__name__)

# -- Constants -----------------------------------------------------------------

DELAY_BARS: list[int] = [3, 6]

SL_MODELS: list[str] = [
    "CANDLE_LOW",
    "CANDLE_LOW_PLUS_0_25",
    "ATR_0_5",
    "ATR_1_0",
    "AOI_NEAR",
    "AOI_FAR",
]

RR_MULTIPLES: list[float] = [1.2, 1.5, 2.0, 2.2, 2.5]

MT5_1H: int = 16385
OUTCOME_WINDOW_BARS: int = 120
CANDLE_LOOKBACK: int = 1000
MIN_SL_ATR: float = 0.05    # discard CANDLE_LOW on near-doji bars
BATCH_SIZE: int = 100

# -- SQL -----------------------------------------------------------------------

_FETCH_SQL = f"""
    SELECT
        es.id,
        es.symbol,
        es.signal_time,
        es.direction,
        es.entry_price,
        es.atr_1h,
        sg.aoi_near_edge_atr,
        sg.aoi_far_edge_atr
    FROM {SCHEMA_NAME}.entry_signal        es
    JOIN {SCHEMA_NAME}.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    WHERE es.is_break_candle_last = TRUE
      AND es.sl_model_version     = 'CHECK_GEO'
      {{year_filter}}
      {{signal_filter}}
    ORDER BY es.signal_time ASC
"""

_INSERT_SQL = f"""
    INSERT INTO {SCHEMA_NAME}.delayed_entry_outcome (
        entry_signal_id, delay_bars, sl_model, rr_multiple,
        delay_return_atr, sl_dist_atr, exit_reason, bars_to_exit, return_r
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (entry_signal_id, delay_bars, sl_model, rr_multiple) DO NOTHING
"""

# -- Data models ---------------------------------------------------------------

@dataclass(frozen=True)
class SignalRow:
    signal_id: int
    symbol: str
    signal_time: object
    direction: TrendDirection
    entry_price: float
    atr_1h: float
    aoi_near_edge_atr: float
    aoi_far_edge_atr: float


@dataclass
class Stats:
    total: int = 0
    processed: int = 0
    rows_written: int = 0
    skip_no_candles: int = 0
    skip_time_match: int = 0
    skip_no_future: int = 0

# -- DB helpers ----------------------------------------------------------------

def fetch_signals(
    year: Optional[int],
    signal_id: Optional[int],
) -> list[SignalRow]:
    year_filter   = f"AND EXTRACT(YEAR FROM es.signal_time) = {year}" if year else ""
    signal_filter = f"AND es.id = {signal_id}" if signal_id else ""
    sql  = _FETCH_SQL.format(year_filter=year_filter, signal_filter=signal_filter)
    rows = DBExecutor.fetch_all(sql, context="backfill_delayed_fetch")

    result: list[SignalRow] = []
    for row in rows:
        sid, symbol, signal_time_db, direction_str, entry_price, atr_1h, aoi_near, aoi_far = row

        if signal_time_db.tzinfo is None:
            signal_time_utc = signal_time_db.replace(tzinfo=timezone.utc)
        else:
            signal_time_utc = signal_time_db.astimezone(timezone.utc)

        direction = TrendDirection.from_raw(direction_str)
        if direction is None:
            logger.warning("Signal %d has unknown direction '%s' -- skipping", sid, direction_str)
            continue

        result.append(SignalRow(
            signal_id=int(sid),
            symbol=symbol,
            signal_time=signal_time_utc,
            direction=direction,
            entry_price=float(entry_price),
            atr_1h=float(atr_1h),
            aoi_near_edge_atr=float(aoi_near),
            aoi_far_edge_atr=float(aoi_far),
        ))
    return result


def flush(batch: list[tuple]) -> int:
    if not batch:
        return 0
    DBExecutor.execute_many(_INSERT_SQL, batch, context="backfill_delayed_insert")
    return len(batch)

# -- SL geometry ---------------------------------------------------------------

def _sl_dist(
    sl_model: str,
    direction: TrendDirection,
    delay_close: float,
    delay_low: float,
    delay_high: float,
    atr: float,
    delay_return_atr: float,
    aoi_near_atr: float,
    aoi_far_atr: float,
) -> Optional[float]:
    """Return SL distance in ATR from delay bar close, or None if invalid."""
    is_bull = direction == TrendDirection.BULLISH

    if sl_model == "CANDLE_LOW":
        dist = (delay_close - delay_low) / atr if is_bull else (delay_high - delay_close) / atr

    elif sl_model == "CANDLE_LOW_PLUS_0_25":
        candle = (delay_close - delay_low) / atr if is_bull else (delay_high - delay_close) / atr
        dist = candle + 0.25

    elif sl_model == "ATR_0_5":
        dist = 0.5

    elif sl_model == "ATR_1_0":
        dist = 1.0

    elif sl_model == "AOI_NEAR":
        # Distance from delayed entry back to the (fixed) AOI near edge.
        # Since entry moved favorably by delay_return_atr ATR away from original
        # entry, and AOI near edge is aoi_near_atr ATR from original entry in
        # the adverse direction: total risk = delay_return_atr + aoi_near_atr.
        dist = delay_return_atr + aoi_near_atr

    elif sl_model == "AOI_FAR":
        dist = delay_return_atr + aoi_far_atr

    else:
        return None

    return dist if dist >= MIN_SL_ATR else None

# -- Forward scanner -----------------------------------------------------------

def _scan(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    new_entry: float,
    sl_dist_atr: float,
    rr: float,
    atr: float,
    is_bull: bool,
) -> tuple[str, int, float]:
    """Vectorised bar-by-bar scan for first SL or TP hit after delay entry."""
    sl_price = new_entry - sl_dist_atr * atr if is_bull else new_entry + sl_dist_atr * atr
    tp_price = new_entry + sl_dist_atr * rr * atr if is_bull else new_entry - sl_dist_atr * rr * atr

    sl_hits = lows <= sl_price if is_bull else highs >= sl_price
    tp_hits = highs >= tp_price if is_bull else lows <= tp_price

    sl_idx = int(np.argmax(sl_hits)) if sl_hits.any() else len(lows)
    tp_idx = int(np.argmax(tp_hits)) if tp_hits.any() else len(highs)

    has_sl = bool(sl_hits.any())
    has_tp = bool(tp_hits.any())

    # SL priority on same bar (conservative)
    if has_sl and (not has_tp or sl_idx <= tp_idx):
        return "SL", sl_idx + 1, -1.0
    if has_tp:
        return "TP", tp_idx + 1, rr

    # TIMEOUT -- partial R at last close
    partial_r = (closes[-1] - new_entry) / (sl_dist_atr * atr) if is_bull \
        else (new_entry - closes[-1]) / (sl_dist_atr * atr)
    return "TIMEOUT", len(lows), float(round(partial_r, 4))

# -- Per-signal logic ----------------------------------------------------------

def process_signal(s: SignalRow, stats: Stats) -> list[tuple]:
    end_time = s.signal_time + timedelta(hours=OUTCOME_WINDOW_BARS)
    candles  = fetch_data(s.symbol, MT5_1H, lookback=CANDLE_LOOKBACK, end_date=end_time)

    if candles is None or candles.empty:
        stats.skip_no_candles += 1
        return []

    candles["time"] = pd.to_datetime(candles["time"], utc=True)
    candles.set_index("time", inplace=True)

    if s.signal_time not in candles.index:
        stats.skip_time_match += 1
        return []

    future = candles[candles.index > s.signal_time].iloc[:OUTCOME_WINDOW_BARS]

    if len(future) < max(DELAY_BARS) + 1:
        stats.skip_no_future += 1
        return []

    highs_all  = future["high"].values.astype(float)
    lows_all   = future["low"].values.astype(float)
    closes_all = future["close"].values.astype(float)

    is_bull = s.direction == TrendDirection.BULLISH
    rows: list[tuple] = []

    for delay in DELAY_BARS:
        if len(future) <= delay:
            continue

        dc = future.iloc[delay - 1]
        delay_close = float(dc["close"])
        delay_low   = float(dc["low"])
        delay_high  = float(dc["high"])

        delay_return_atr = (
            (delay_close - s.entry_price) / s.atr_1h if is_bull
            else (s.entry_price - delay_close) / s.atr_1h
        )

        if delay_return_atr <= 0.0:
            continue  # price not favorable -- no entry

        # Forward arrays start one bar after delay bar
        fwd_highs  = highs_all[delay:]
        fwd_lows   = lows_all[delay:]
        fwd_closes = closes_all[delay:]

        if len(fwd_highs) == 0:
            continue

        for sl_model in SL_MODELS:
            sl_dist = _sl_dist(
                sl_model, s.direction,
                delay_close, delay_low, delay_high,
                s.atr_1h, delay_return_atr,
                s.aoi_near_edge_atr, s.aoi_far_edge_atr,
            )
            if sl_dist is None:
                continue

            for rr in RR_MULTIPLES:
                exit_reason, bars_to_exit, return_r = _scan(
                    fwd_highs, fwd_lows, fwd_closes,
                    delay_close, sl_dist, rr, s.atr_1h, is_bull,
                )
                rows.append((
                    int(s.signal_id), int(delay), str(sl_model), float(rr),
                    float(round(delay_return_atr, 4)),
                    float(round(sl_dist, 4)),
                    str(exit_reason),
                    int(bars_to_exit),
                    float(round(return_r, 4)),
                ))

    stats.processed += 1
    return rows

# -- Entry point ---------------------------------------------------------------

def run(year: Optional[int], signal_id: Optional[int]) -> None:
    logger.info("Fetching signals (year=%s, signal_id=%s)...", year, signal_id)
    signals = fetch_signals(year, signal_id)

    if not signals:
        logger.error("No signals found -- check filters and DB connection.")
        return

    stats = Stats(total=len(signals))
    logger.info("Found %d signals to process.", stats.total)

    pending: list[tuple] = []

    for i, s in enumerate(signals, start=1):
        pending.extend(process_signal(s, stats))

        if i % BATCH_SIZE == 0 or i == stats.total:
            stats.rows_written += flush(pending)
            pending.clear()
            logger.info(
                "[%d/%d] processed=%d  written=%d  "
                "skip(nc=%d tm=%d nf=%d)",
                i, stats.total, stats.processed, stats.rows_written,
                stats.skip_no_candles, stats.skip_time_match, stats.skip_no_future,
            )

    logger.info(
        "Done. processed=%d  written=%d  skipped=%d",
        stats.processed, stats.rows_written,
        stats.skip_no_candles + stats.skip_time_match + stats.skip_no_future,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill delayed_entry_outcome.")
    parser.add_argument("--year", type=int, default=None,
                        help="Restrict to one year, e.g. 2021.")
    parser.add_argument("--signal-id", type=int, default=None,
                        help="Process a single signal (for testing).")
    args = parser.parse_args()
    run(year=args.year, signal_id=args.signal_id)

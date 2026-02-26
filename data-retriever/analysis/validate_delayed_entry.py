"""
validate_delayed_entry.py — Detailed validation of candle alignment for a single signal.

Logs every candle timestamp used in the backfill to confirm no bias.

Usage:
    cd data-retriever && python analysis/validate_delayed_entry.py --signal-id 444462
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from database.executor import DBExecutor
from externals.data_fetcher import fetch_data
from models import TrendDirection
from replay.config import SCHEMA_NAME
from logger import get_logger

logger = get_logger(__name__)

DELAY_BARS = [3, 6]
MT5_1H = 16385
OUTCOME_WINDOW_BARS = 120
CANDLE_LOOKBACK = 1000
MIN_SL_ATR = 0.05

_FETCH_SQL = f"""
    SELECT
        es.id,
        es.symbol,
        es.signal_time,
        es.direction,
        es.entry_price,
        es.atr_tf,
        sg.aoi_near_edge_atr,
        sg.aoi_far_edge_atr
    FROM {SCHEMA_NAME}.entry_signal        es
    JOIN {SCHEMA_NAME}.sl_geometry_unbiased sg ON sg.entry_signal_id = es.id
    WHERE es.id = %s
"""


def validate(signal_id: int) -> None:
    rows = DBExecutor.fetch_all(_FETCH_SQL % signal_id, context="validate_fetch")
    if not rows:
        logger.error("Signal %d not found in DB (or missing sl_geometry_unbiased row)", signal_id)
        return

    row = rows[0]
    sid, symbol, signal_time_db, direction_str, entry_price_db, atr_tf_db, aoi_near_db, aoi_far_db = row

    if signal_time_db.tzinfo is None:
        signal_time = signal_time_db.replace(tzinfo=timezone.utc)
    else:
        signal_time = signal_time_db.astimezone(timezone.utc)

    direction = TrendDirection.from_raw(direction_str)
    entry_price = float(entry_price_db)
    atr_tf = float(atr_tf_db)
    aoi_near = float(aoi_near_db)
    aoi_far = float(aoi_far_db)
    is_bull = direction == TrendDirection.BULLISH

    logger.info("=" * 70)
    logger.info("SIGNAL METADATA")
    logger.info("  signal_id   : %d", sid)
    logger.info("  symbol      : %s", symbol)
    logger.info("  direction   : %s  (is_bull=%s)", direction_str, is_bull)
    logger.info("  signal_time : %s  (this is T open time, 1H bar = [T, T+1h))", signal_time)
    logger.info("  entry_price : %.5f  (= close of signal bar T)", entry_price)
    logger.info("  atr_tf      : %.5f", atr_tf)
    logger.info("  aoi_near_atr: %.4f ATR  (dist entry -> AOI near edge)", aoi_near)
    logger.info("  aoi_far_atr : %.4f ATR  (dist entry -> AOI far edge)", aoi_far)

    # ── Fetch candles ──────────────────────────────────────────────────────────
    end_time = signal_time + timedelta(hours=OUTCOME_WINDOW_BARS)
    logger.info("=" * 70)
    logger.info("CANDLE FETCH")
    logger.info("  fetch end_date   : %s  (signal_time + %dh)", end_time, OUTCOME_WINDOW_BARS)
    logger.info("  NOTE: MT5 copy_rates_range is [start, end) exclusive on end.")
    logger.info("  Last candle expected: open_time = signal_time + %dh", OUTCOME_WINDOW_BARS - 1)

    candles = fetch_data(symbol, MT5_1H, lookback=CANDLE_LOOKBACK, end_date=end_time)
    if candles is None or candles.empty:
        logger.error("No candles returned from MT5 for %s", symbol)
        return

    candles["time"] = pd.to_datetime(candles["time"], utc=True)
    candles.set_index("time", inplace=True)

    logger.info("  Total candles fetched (after tail(%d)): %d", CANDLE_LOOKBACK, len(candles))
    logger.info("  First candle open_time: %s", candles.index[0])
    logger.info("  Last  candle open_time: %s", candles.index[-1])

    # ── Signal bar (T) ────────────────────────────────────────────────────────
    logger.info("=" * 70)
    logger.info("SIGNAL BAR LOOKUP  (T)")
    if signal_time not in candles.index:
        logger.error("  signal_time %s NOT IN candle index — time mismatch!", signal_time)
        # Show nearest candles
        idx_pos = candles.index.searchsorted(signal_time)
        logger.error("  Nearest candle before: %s", candles.index[max(0, idx_pos - 1)])
        logger.error("  Nearest candle after : %s", candles.index[min(len(candles) - 1, idx_pos)])
        return

    t_bar = candles.loc[signal_time]
    logger.info("  T open_time : %s  (matches signal_time) OK", signal_time)
    logger.info("  T open      : %.5f", float(t_bar["open"]))
    logger.info("  T high      : %.5f", float(t_bar["high"]))
    logger.info("  T low       : %.5f", float(t_bar["low"]))
    logger.info("  T close     : %.5f  <- entry_price from DB should match", float(t_bar["close"]))
    logger.info("  DB entry_price: %.5f  match=%s",
                entry_price, abs(float(t_bar["close"]) - entry_price) < 1e-7)

    # ── Future bars ───────────────────────────────────────────────────────────
    future = candles[candles.index > signal_time].iloc[:OUTCOME_WINDOW_BARS]
    logger.info("=" * 70)
    logger.info("FUTURE BARS  (candles after T, first %d)", OUTCOME_WINDOW_BARS)
    logger.info("  Count: %d", len(future))
    logger.info("  T+1  open_time: %s  (future.iloc[0])", future.index[0])
    logger.info("  T+2  open_time: %s  (future.iloc[1])", future.index[1] if len(future) > 1 else "N/A")
    logger.info("  T+3  open_time: %s  (future.iloc[2])", future.index[2] if len(future) > 2 else "N/A")
    logger.info("  T+6  open_time: %s  (future.iloc[5])", future.index[5] if len(future) > 5 else "N/A")
    logger.info("  T+7  open_time: %s  (future.iloc[6], first bar scanned after delay=6)",
                future.index[6] if len(future) > 6 else "N/A")
    logger.info("  Last open_time: %s  (future.iloc[-1])", future.index[-1])
    logger.info("  Expected last : signal_time + %dh = %s",
                OUTCOME_WINDOW_BARS - 1, signal_time + timedelta(hours=OUTCOME_WINDOW_BARS - 1))

    # ── Per-delay validation ───────────────────────────────────────────────────
    for delay in DELAY_BARS:
        logger.info("=" * 70)
        logger.info("DELAY = %d BARS", delay)

        if len(future) <= delay:
            logger.warning("  Not enough future bars (%d) for delay=%d — skip", len(future), delay)
            continue

        dc = future.iloc[delay - 1]
        delay_bar_time = future.index[delay - 1]
        delay_close = float(dc["close"])
        delay_low   = float(dc["low"])
        delay_high  = float(dc["high"])

        expected_delay_time = signal_time + timedelta(hours=delay)
        time_ok = delay_bar_time == expected_delay_time

        logger.info("  Delay bar (future.iloc[%d])", delay - 1)
        logger.info("    open_time         : %s", delay_bar_time)
        logger.info("    expected open_time: %s  match=%s", expected_delay_time, time_ok)
        if not time_ok:
            logger.warning("    TIME MISMATCH — gap in candles (weekend/holiday)?")
        logger.info("    open  : %.5f", float(dc["open"]))
        logger.info("    high  : %.5f", float(dc["high"]))
        logger.info("    low   : %.5f", float(dc["low"]))
        logger.info("    close : %.5f  <- delayed entry price", delay_close)

        delay_return_atr = (
            (delay_close - entry_price) / atr_tf if is_bull
            else (entry_price - delay_close) / atr_tf
        )
        logger.info("  delay_return_atr: %.4f  (>0 = favorable, triggers entry)", delay_return_atr)

        if delay_return_atr <= 0.0:
            logger.info("  ENTRY SKIPPED (not favorable)")
            continue

        # Forward scan window
        fwd_start_idx = delay
        fwd_start_time = future.index[fwd_start_idx] if len(future) > fwd_start_idx else None
        expected_fwd_start = signal_time + timedelta(hours=delay + 1)
        logger.info("  Forward scan starts at future.iloc[%d]", fwd_start_idx)
        logger.info("    open_time         : %s", fwd_start_time)
        logger.info("    expected open_time: %s  match=%s",
                    expected_fwd_start, fwd_start_time == expected_fwd_start)
        logger.info("    bars available to scan: %d", len(future) - fwd_start_idx)

        # SL models
        logger.info("  SL MODELS (entry=%.5f  atr=%.5f):", delay_close, atr_tf)
        sl_models = {
            "CANDLE_LOW":          (delay_close - delay_low) / atr_tf if is_bull else (delay_high - delay_close) / atr_tf,
            "CANDLE_LOW+0.25":     ((delay_close - delay_low) / atr_tf if is_bull else (delay_high - delay_close) / atr_tf) + 0.25,
            "ATR_0_5":             0.5,
            "ATR_1_0":             1.0,
            "AOI_NEAR":            delay_return_atr + aoi_near,
            "AOI_FAR":             delay_return_atr + aoi_far,
        }
        for name, dist in sl_models.items():
            if dist < MIN_SL_ATR:
                logger.info("    %-20s dist=%.4f ATR  SKIPPED (< MIN_SL_ATR)", name, dist)
                continue
            sl_price = delay_close - dist * atr_tf if is_bull else delay_close + dist * atr_tf
            tp_price = delay_close + dist * 2.0 * atr_tf if is_bull else delay_close - dist * 2.0 * atr_tf
            logger.info("    %-20s dist=%.4f ATR  SL=%.5f  TP(2R)=%.5f",
                        name, dist, sl_price, tp_price)

        # AOI SL sanity check: should resolve to aoi_high/aoi_low
        near_atr_abs = aoi_near * atr_tf
        far_atr_abs  = aoi_far  * atr_tf
        if is_bull:
            aoi_high_implied = entry_price - near_atr_abs  # entry_price - (entry_price - aoi_high) = aoi_high
            aoi_low_implied  = entry_price - far_atr_abs
        else:
            aoi_high_implied = entry_price + far_atr_abs
            aoi_low_implied  = entry_price + near_atr_abs

        aoi_near_sl = delay_close - (delay_return_atr + aoi_near) * atr_tf if is_bull \
                      else delay_close + (delay_return_atr + aoi_near) * atr_tf
        aoi_far_sl  = delay_close - (delay_return_atr + aoi_far) * atr_tf if is_bull \
                      else delay_close + (delay_return_atr + aoi_far) * atr_tf

        logger.info("  AOI geometry verification:")
        logger.info("    AOI_NEAR SL resolves to: %.5f  (should = aoi_high implied %.5f  match=%s)",
                    aoi_near_sl, aoi_high_implied, abs(aoi_near_sl - aoi_high_implied) < 1e-7)
        logger.info("    AOI_FAR  SL resolves to: %.5f  (should = aoi_low  implied %.5f  match=%s)",
                    aoi_far_sl, aoi_low_implied, abs(aoi_far_sl - aoi_low_implied) < 1e-7)

    logger.info("=" * 70)
    logger.info("VALIDATION COMPLETE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate delayed entry candle alignment.")
    parser.add_argument("--signal-id", type=int, required=True)
    args = parser.parse_args()
    validate(args.signal_id)

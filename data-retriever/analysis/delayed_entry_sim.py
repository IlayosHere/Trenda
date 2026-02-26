#!/usr/bin/env python3
"""
delayed_entry_sim.py — Option A: Delayed entry simulation using checkpoint returns.

Simulates entering trades at bar 3 or 6 (if positive at that bar) with a
fixed ATR stop instead of the original signal-candle SL.

CAVEAT: Only 6 discrete checkpoints are available. SL/TP hits between bars
are not observed. Actual SL hit rate is higher than computed — results are
optimistically biased, especially for tight SLs relative to bar spacing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
import psycopg2

from configuration.db_config import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

CHECKPOINT_BARS: list[int] = [3, 6, 12, 24, 48, 72]
DELAY_BARS: list[int] = [0, 3, 6]
SL_SIZES: list[float] = [0.5, 1.0, 1.5, 2.0]
RR: float = 2.0

GROUPS: dict[str, list[str]] = {
    "jpy":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "comm": ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

SYMBOL_TO_GROUP: dict[str, str] = {
    sym: grp for grp, syms in GROUPS.items() for sym in syms
}

SQL = """
SELECT
    cr.bars_after,
    cr.return_atr,
    so.first_extreme,
    es.id        AS signal_id,
    es.symbol,
    es.direction,
    es.signal_time,
    esi.sl_model,
    esi.exit_reason
FROM trenda_replay.checkpoint_return            cr
JOIN trenda_replay.signal_outcome               so  ON so.id            = cr.signal_outcome_id
JOIN trenda_replay.entry_signal                 es  ON es.id            = so.entry_signal_id
JOIN trenda_replay.exit_simulation_unbiased     esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
  AND esi.rr_multiple         = 2.0
  AND esi.sl_model            != 'SL_AOI_NEAR'
ORDER BY es.signal_time, cr.bars_after
"""

# ── Data loading ───────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    logger.info("Loading checkpoint data from DB...")
    conn = psycopg2.connect(**POSTGRES_DB)
    try:
        cur = conn.cursor()
        cur.execute(SQL)
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    df = pd.DataFrame(rows, columns=cols)
    logger.info("Loaded %d rows.", len(df))

    df["return_atr"] = df["return_atr"].astype(float)
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["group"] = df["symbol"].map(SYMBOL_TO_GROUP).fillna("other")
    df["cell"] = df["group"].str.upper() + "|" + df["direction"].str[:4].str.upper()
    df["is_win"] = df["exit_reason"] == "TP"
    return df


def pivot_checkpoints(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot long-format to wide: one row per (signal_id, sl_model)."""
    meta = (
        df.groupby(["signal_id", "sl_model"])
        .agg(cell=("cell", "first"), is_win=("is_win", "first"),
             first_extreme=("first_extreme", "first"))
        .reset_index()
    )
    wide = df.pivot_table(
        index=["signal_id", "sl_model"],
        columns="bars_after",
        values="return_atr",
        aggfunc="first",
    ).reset_index()
    wide.columns = [f"cr_{c}" if isinstance(c, int) else c for c in wide.columns]
    return meta.merge(wide, on=["signal_id", "sl_model"])

# ── Simulation core ────────────────────────────────────────────────────────────

def simulate(
    pivoted: pd.DataFrame,
    delay_bar: int,
    sl_atr: float,
) -> dict:
    """Simulate delayed entry with fixed ATR SL on the given (pre-filtered) df."""
    tp_atr = sl_atr * RR
    bars_after_delay = [b for b in CHECKPOINT_BARS if b > delay_bar]

    if delay_bar == 0:
        valid = pivoted.copy()
        base = pd.Series(0.0, index=valid.index)
    else:
        delay_col = f"cr_{delay_bar}"
        valid = pivoted.dropna(subset=[delay_col])
        n_universe = len(valid)
        valid = valid[valid[delay_col] > 0].copy()
        base = valid[delay_col]

    n_universe = len(pivoted) if delay_bar == 0 else n_universe  # type: ignore[assignment]
    n_entered = len(valid)

    if n_entered == 0:
        return {"n_universe": n_universe, "n_entered": 0, "entry_rate_pct": 0.0,
                "win_rate_pct": 0.0, "loss_rate_pct": 0.0,
                "open_rate_pct": 0.0, "ev_r": 0.0}

    # Forward returns relative to delay bar close
    fwd_cols: list[str] = []
    for bar in bars_after_delay:
        cr_col = f"cr_{bar}"
        if cr_col in valid.columns:
            fwd_col = f"fwd_{bar}"
            valid[fwd_col] = valid[cr_col].values - base.values
            fwd_cols.append(fwd_col)

    # Walk checkpoints in order; first threshold crossed wins
    outcome = pd.Series("open", index=valid.index)
    decided = pd.Series(False, index=valid.index)

    for col in fwd_cols:
        fwd = valid[col]
        hit_sl = ~decided & (fwd <= -sl_atr)
        hit_tp = ~decided & (fwd >= tp_atr)
        outcome[hit_sl] = "SL"
        outcome[hit_tp] = "TP"
        decided = decided | hit_sl | hit_tp

    n_tp   = (outcome == "TP").sum()
    n_sl   = (outcome == "SL").sum()
    n_open = (outcome == "open").sum()

    win_rate  = n_tp / n_entered
    loss_rate = n_sl / n_entered
    open_rate = n_open / n_entered
    # EV counts "open" trades as 0 (unresolved); conservative
    ev_r = win_rate * RR - loss_rate * 1.0

    return {
        "n_universe":     n_universe,
        "n_entered":      n_entered,
        "entry_rate_pct": n_entered / n_universe * 100,
        "win_rate_pct":   win_rate  * 100,
        "loss_rate_pct":  loss_rate * 100,
        "open_rate_pct":  open_rate * 100,
        "ev_r":           ev_r,
    }

# ── Output ─────────────────────────────────────────────────────────────────────

def print_table(pivoted: pd.DataFrame, label: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"DELAYED ENTRY SIMULATION — {label}")
    print(f"{'=' * 72}")
    print("CAVEAT: Intra-checkpoint path unobserved. SL underestimated (optimistic).\n")

    hdr = (
        f"  {'delay':>8}  {'entry%':>7}  {'n_entered':>10}  "
        f"{'win%':>7}  {'loss%':>7}  {'open%':>7}  {'EV_R':>7}"
    )
    sep = "  " + "-" * (len(hdr) - 2)

    for sl_atr in SL_SIZES:
        print(f"--- SL={sl_atr:.1f} ATR | TP={sl_atr * RR:.1f} ATR ---")
        print(hdr)
        print(sep)
        for delay in DELAY_BARS:
            r = simulate(pivoted, delay, sl_atr)
            if r["n_entered"] == 0:
                continue
            tag = f"{delay}h (all)" if delay == 0 else f"{delay}h (pos)"
            print(
                f"  {tag:>8}  {r['entry_rate_pct']:>6.1f}%  {r['n_entered']:>10,}  "
                f"{r['win_rate_pct']:>6.1f}%  {r['loss_rate_pct']:>6.1f}%  "
                f"{r['open_rate_pct']:>6.1f}%  {r['ev_r']:>+7.3f}"
            )
        print()

# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Delayed entry simulation (Option A).")
    parser.add_argument("--cell", default=None,
                        help="Filter to one cell, e.g. 'jpy|bear'. "
                             "Omit for all cells + per-cell breakdown.")
    args = parser.parse_args()

    df = load_data()
    logger.info("Pivoting checkpoints...")
    pivoted = pivot_checkpoints(df)
    logger.info("Pivoted to %d observations.", len(pivoted))

    if args.cell:
        cell_key = args.cell.upper()
        sub = pivoted[pivoted["cell"] == cell_key]
        print_table(sub, cell_key)
    else:
        print_table(pivoted, "ALL CELLS")
        for cell in sorted(pivoted["cell"].unique()):
            print_table(pivoted[pivoted["cell"] == cell], cell)

    logger.info("Done.")


if __name__ == "__main__":
    main()

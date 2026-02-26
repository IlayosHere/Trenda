#!/usr/bin/env python3
"""
checkpoint_analysis.py — Checkpoint return curve analysis (STEP 1B).

Analyses A–E on fixed-bar return curves to determine when wins/losses
diverge, whether early direction predicts outcome, and winner speed.
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

# ── Constants ──────────────────────────────────────────────────────────────────

CHECKPOINT_BARS: list[int] = [3, 6, 12, 24, 48, 72]

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
    so.mfe_atr,
    so.mae_atr,
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

    for col in ("return_atr", "mfe_atr", "mae_atr"):
        df[col] = df[col].astype(float)

    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"] = df["signal_time"].dt.year
    df["group"] = df["symbol"].map(SYMBOL_TO_GROUP).fillna("other")
    df["cell"] = df["group"].str.upper() + "|" + df["direction"].str[:4].str.upper()
    df["is_win"] = df["exit_reason"] == "TP"
    return df

# ── Helpers ────────────────────────────────────────────────────────────────────

def _curve_table(df: pd.DataFrame, label: str) -> None:
    print(f"\n{label}")
    hdr = (
        f"  {'bar':>4}  {'wins_med':>9} {'wins_p25':>9} {'wins_p75':>9}  "
        f"{'loss_med':>9} {'loss_p25':>9} {'loss_p75':>9}  {'gap':>7}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    wins   = df[df["is_win"]]
    losses = df[~df["is_win"]]

    for bar in CHECKPOINT_BARS:
        w = wins[wins["bars_after"] == bar]["return_atr"]
        l = losses[losses["bars_after"] == bar]["return_atr"]
        if w.empty or l.empty:
            continue
        wm, wp25, wp75 = w.median(), w.quantile(0.25), w.quantile(0.75)
        lm, lp25, lp75 = l.median(), l.quantile(0.25), l.quantile(0.75)
        print(
            f"  {bar:>4}  {wm:>9.3f} {wp25:>9.3f} {wp75:>9.3f}  "
            f"{lm:>9.3f} {lp25:>9.3f} {lp75:>9.3f}  {wm - lm:>7.3f}"
        )

# ── Analysis A — All cells combined ───────────────────────────────────────────

def analysis_a(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("ANALYSIS A - Return curve: wins vs losses (ALL cells combined)")
    print("=" * 70)
    _curve_table(df, "all cells")

# ── Analysis B — Per cell ──────────────────────────────────────────────────────

def analysis_b(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("ANALYSIS B - Per-cell return curve")
    print("=" * 70)
    for cell in sorted(df["cell"].unique()):
        _curve_table(df[df["cell"] == cell], f"--- {cell} ---")

# ── Analysis C — Positive at bar N -> win rate ────────────────────────────────

def analysis_c(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("ANALYSIS C - 'Positive at bar N' -> win rate")
    print("=" * 70)

    baseline = df[df["bars_after"] == CHECKPOINT_BARS[0]]["is_win"].mean() * 100

    hdr = (
        f"  {'bar':>4}  {'n_pos':>7} {'pos_win%':>9}  "
        f"{'n_neg':>7} {'neg_win%':>9}  {'lift_pp':>8}  {'baseline':>9}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    for bar in CHECKPOINT_BARS:
        sub  = df[df["bars_after"] == bar]
        pos  = sub[sub["return_atr"] > 0]
        neg  = sub[sub["return_atr"] <= 0]
        if pos.empty or neg.empty:
            continue
        pos_win = pos["is_win"].mean() * 100
        neg_win = neg["is_win"].mean() * 100
        lift    = pos_win - neg_win
        print(
            f"  {bar:>4}  {len(pos):>7} {pos_win:>8.1f}%  "
            f"{len(neg):>7} {neg_win:>8.1f}%  {lift:>7.1f}pp  {baseline:>8.1f}%"
        )

# ── Analysis D — MFE_FIRST losers: reversal timing ────────────────────────────

def analysis_d(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("ANALYSIS D - MFE_FIRST losers: when do they reverse?")
    print("=" * 70)

    mfe_loss = df[(~df["is_win"]) & (df["first_extreme"] == "MFE_FIRST")]
    mae_loss = df[(~df["is_win"]) & (df["first_extreme"] == "MAE_FIRST")]
    wins     = df[df["is_win"]]

    hdr = (
        f"  {'bar':>4}  {'MFE_FIRST losers':>17}  "
        f"{'MAE_FIRST losers':>17}  {'winners':>10}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    reversal_bar: Optional[int] = None
    for bar in CHECKPOINT_BARS:
        mfl_med = mfe_loss[mfe_loss["bars_after"] == bar]["return_atr"].median()
        mal_med = mae_loss[mae_loss["bars_after"] == bar]["return_atr"].median()
        w_med   = wins[wins["bars_after"] == bar]["return_atr"].median()
        print(f"  {bar:>4}  {mfl_med:>17.3f}  {mal_med:>17.3f}  {w_med:>10.3f}")
        if reversal_bar is None and mfl_med <= 0:
            reversal_bar = bar

    if reversal_bar is not None:
        print(f"\n  MFE_FIRST losers median crosses zero at: bar {reversal_bar}")
    else:
        print("\n  MFE_FIRST losers median stays positive through all checkpoint bars.")

# ── Analysis E — Winner speed ──────────────────────────────────────────────────

def analysis_e(df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("ANALYSIS E - Winner speed")
    print("=" * 70)

    wins = df[df["is_win"]]

    hdr = f"  {'bar':>4}  {'%>+0.5 ATR':>12}  {'%>+1.0 ATR':>12}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    for bar in [3, 6, 12, 24]:
        sub = wins[wins["bars_after"] == bar]["return_atr"]
        if sub.empty:
            continue
        p05 = (sub > 0.5).mean() * 100
        p10 = (sub > 1.0).mean() * 100
        print(f"  {bar:>4}  {p05:>11.1f}%  {p10:>11.1f}%")

# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Checkpoint return curve analysis.")
    parser.add_argument("--cell", default=None, help="Filter to one cell, e.g. 'jpy|bear'")
    args = parser.parse_args()

    df = load_data()

    if args.cell:
        cell_key = args.cell.upper()
        df = df[df["cell"] == cell_key]
        logger.info("Filtered to cell=%s: %d rows.", cell_key, len(df))

    analysis_a(df)
    analysis_b(df)
    analysis_c(df)
    analysis_d(df)
    analysis_e(df)

    logger.info("Done.")


if __name__ == "__main__":
    main()

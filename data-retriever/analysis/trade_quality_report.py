#!/usr/bin/env python3
"""
trade_quality_report.py — Trade path quality inspection tool.

Examines MFE/MAE trade paths for structural differences between winners and
losers per cell x year. Qualitative inspection only — no statistical filtering.
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

NUMERIC_COLS: list[str] = [
    "trend_alignment_strength",
    "max_retest_penetration_atr",
    "bars_between_retest_and_break",
    "htf_range_position_mid",
    "htf_range_position_high",
    "session_directional_bias",
    "break_close_location",
    "break_impulse_range_atr",
    "break_impulse_body_atr",
    "retest_candle_body_penetration",
    "aoi_height_atr",
    "distance_to_next_htf_obstacle_atr",
    "distance_from_last_impulse_atr",
    "recent_trend_payoff_atr_24h",
    "recent_trend_payoff_atr_48h",
    "aoi_time_since_last_touch",
    "aoi_last_reaction_strength",
    "htf_range_size_mid_atr",
    "aoi_midpoint_range_position_mid",
    "trend_age_bars_1h",
    "trend_age_impulses",
    "opp_extreme",
    "signal_candle_range_atr",
    "signal_candle_body_atr",
    "aoi_near_edge_atr",
    "aoi_far_edge_atr",
    "mfe_atr",
    "mae_atr",
    "return_r",
    "hour_of_day_utc",
    "aoi_touch_count_since_creation",
]

BASE_SQL = """
SELECT
    es.id AS signal_id,
    es.signal_time,
    es.symbol,
    es.direction,
    es.trend_alignment_strength,
    es.hour_of_day_utc,
    es.aoi_touch_count_since_creation,
    es.max_retest_penetration_atr,
    es.bars_between_retest_and_break,
    es.conflicted_tf,
    pec.htf_range_position_mid,
    pec.htf_range_position_high,
    pec.session_directional_bias,
    pec.break_close_location,
    pec.break_impulse_range_atr,
    pec.break_impulse_body_atr,
    pec.retest_candle_body_penetration,
    pec.aoi_height_atr,
    pec.distance_to_next_htf_obstacle_atr,
    pec.distance_from_last_impulse_atr,
    pec.recent_trend_payoff_atr_24h,
    pec.recent_trend_payoff_atr_48h,
    pec.aoi_time_since_last_touch,
    pec.aoi_last_reaction_strength,
    pec.htf_range_size_mid_atr,
    pec.aoi_midpoint_range_position_mid,
    pec.trend_age_bars_1h,
    pec.trend_age_impulses,
    sg.signal_candle_opposite_extreme_atr AS opp_extreme,
    sg.signal_candle_range_atr,
    sg.signal_candle_body_atr,
    sg.aoi_near_edge_atr,
    sg.aoi_far_edge_atr,
    so.mfe_atr,
    so.mae_atr,
    so.bars_to_mfe,
    so.bars_to_mae,
    so.first_extreme,
    esi.sl_model,
    esi.exit_reason,
    esi.return_r
FROM trenda_replay.entry_signal              es
JOIN trenda_replay.pre_entry_context_v2      pec ON pec.entry_signal_id = es.id
JOIN trenda_replay.sl_geometry_unbiased      sg  ON sg.entry_signal_id  = es.id
LEFT JOIN trenda_replay.signal_outcome       so  ON so.entry_signal_id  = es.id
JOIN trenda_replay.exit_simulation_unbiased  esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
  AND esi.rr_multiple         = 2.0
ORDER BY es.signal_time
"""

FIRST_EXTREME_LABELS: list[str] = ["MFE_FIRST", "MAE_FIRST", "ONLY_MFE", "ONLY_MAE"]

PATH_COLS: list[str] = ["first_extreme", "mfe_atr", "mae_atr", "bars_to_mfe", "bars_to_mae"]

PRE_ENTRY_COLS: list[str] = [
    "htf_range_position_mid", "htf_range_position_high", "session_directional_bias",
    "break_close_location", "break_impulse_range_atr", "break_impulse_body_atr",
    "retest_candle_body_penetration", "aoi_height_atr",
    "distance_to_next_htf_obstacle_atr", "distance_from_last_impulse_atr",
    "recent_trend_payoff_atr_24h", "recent_trend_payoff_atr_48h",
    "aoi_time_since_last_touch", "aoi_last_reaction_strength",
    "htf_range_size_mid_atr", "aoi_midpoint_range_position_mid",
    "trend_age_bars_1h", "trend_age_impulses",
    "opp_extreme", "signal_candle_range_atr", "signal_candle_body_atr",
    "aoi_near_edge_atr", "aoi_far_edge_atr",
    "trend_alignment_strength", "max_retest_penetration_atr",
    "bars_between_retest_and_break",
]

# ── Data loading ───────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    conn = psycopg2.connect(**POSTGRES_DB)
    try:
        cur = conn.cursor()
        cur.execute(BASE_SQL)
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    df = pd.DataFrame(rows, columns=cols)
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"] = df["signal_time"].dt.year

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: float(x) if x is not None else np.nan)

    grp = df["symbol"].map(SYMBOL_TO_GROUP)
    dir_short = df["direction"].str[:4].str.lower()
    df["cell"] = grp + "|" + dir_short

    df["is_win"] = df["exit_reason"] == "TP"

    return df


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pct(series: pd.Series, label: str) -> float:
    total = len(series)
    if total == 0:
        return 0.0
    return 100.0 * (series == label).sum() / total


def _ratio(mfe: float, mae: float) -> str:
    if np.isnan(mae) or mae == 0.0 or np.isnan(mfe):
        return "n/a"
    return f"{abs(mfe) / abs(mae):.2f}"


def _fmt_val(v: object) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    if isinstance(v, float):
        return f"{v:.4f}"
    if isinstance(v, int):
        return str(v)
    return str(v)


# ── Part A — Per-cell first_extreme summary ────────────────────────────────────

def print_part_a(df: pd.DataFrame, cell_filter: Optional[str]) -> None:
    cells = sorted(df["cell"].dropna().unique())
    if cell_filter:
        cells = [c for c in cells if c == cell_filter]

    print("\n" + "=" * 70)
    print("PART A - Per-cell first_extreme summary")
    print("=" * 70)

    for cell in cells:
        cdf = df[df["cell"] == cell]
        n = len(cdf)
        win_pct = 100.0 * cdf["is_win"].sum() / n if n else 0.0

        wins = cdf[cdf["is_win"]]
        losses = cdf[~cdf["is_win"]]

        print(f"\n=== {cell.upper()}  n={n}  win%={win_pct:.1f}% ===\n")
        print("  first_extreme breakdown:")
        header = f"  {'':20s}  {'WINS':>8s}  {'LOSSES':>8s}"
        print(header)

        for label in FIRST_EXTREME_LABELS:
            w_pct = _pct(wins["first_extreme"], label)
            l_pct = _pct(losses["first_extreme"], label)
            print(f"  {label:20s}  {w_pct:>7.1f}%  {l_pct:>7.1f}%")

        print()
        print("  MFE/MAE ratio (median):")
        w_mfe = wins["mfe_atr"].median()
        w_mae = wins["mae_atr"].median()
        l_mfe = losses["mfe_atr"].median()
        l_mae = losses["mae_atr"].median()
        print(f"    wins:    mfe={w_mfe:>6.2f}  mae={w_mae:>6.2f}  ratio={_ratio(w_mfe, w_mae)}")
        print(f"    losses:  mfe={l_mfe:>6.2f}  mae={l_mae:>6.2f}  ratio={_ratio(l_mfe, l_mae)}")


# ── Part B — Sampled trade detail ─────────────────────────────────────────────

def _print_trade(row: pd.Series, cell: str) -> None:
    label = f"[TP +{row['return_r']:.2f}R]" if row["is_win"] else f"[SL {row['return_r']:.2f}R]"
    sym = row["symbol"]
    sl = row["sl_model"]
    ts = row["signal_time"].strftime("%Y-%m-%d %H:%M")
    year = int(row["year"])
    hour = int(row["hour_of_day_utc"]) if not np.isnan(row.get("hour_of_day_utc", np.nan)) else "?"  # type: ignore[arg-type]
    conflict = str(row["conflicted_tf"]) if row["conflicted_tf"] else "none"

    print("  " + "-" * 66)
    print(f"  {label}  {cell.upper()}   {sym}    {sl}")
    print(f"  {ts}  year={year}  hour={hour}UTC  conflict={conflict}")
    print("  " + "-" * 66)

    print("  --- TRADE PATH ---")
    for col in PATH_COLS:
        val = row.get(col, None)
        print(f"  {col:<30s} {_fmt_val(val)}")

    print()
    print("  --- PRE-ENTRY CONTEXT ---")
    for col in PRE_ENTRY_COLS:
        val = row.get(col, None)
        print(f"  {col:<40s} {_fmt_val(val)}")
    print()


def print_part_b(
    df: pd.DataFrame,
    cell_filter: Optional[str],
    year_filter: Optional[int],
) -> None:
    print("\n" + "=" * 70)
    print("PART B - Sampled trade detail (top 3 winners / bottom 3 losers per cell x year)")
    print("=" * 70)

    cells = sorted(df["cell"].dropna().unique())
    if cell_filter:
        cells = [c for c in cells if c == cell_filter]

    years = sorted(df["year"].dropna().unique())
    if year_filter:
        years = [y for y in years if y == year_filter]

    for cell in cells:
        cdf = df[df["cell"] == cell]
        for year in years:
            ydf = cdf[cdf["year"] == year]
            if ydf.empty:
                continue

            wins = ydf[ydf["is_win"]].nlargest(3, "return_r")
            losses = ydf[~ydf["is_win"]].nsmallest(3, "return_r")

            if wins.empty and losses.empty:
                continue

            print(f"\n{'=' * 70}")
            print(f"  {cell.upper()}  |  year={year}  |  "
                  f"n={len(ydf)}  wins={len(ydf[ydf['is_win']])}  losses={len(ydf[~ydf['is_win']])}")
            print(f"{'=' * 70}")

            if not wins.empty:
                print("\n  >>> TOP WINNERS <<<")
                for _, row in wins.iterrows():
                    _print_trade(row, cell)

            if not losses.empty:
                print("\n  >>> WORST LOSERS <<<")
                for _, row in losses.iterrows():
                    _print_trade(row, cell)


# ── Part C — Aggregate MFE/MAE stability ──────────────────────────────────────

def print_part_c(
    df: pd.DataFrame,
    cell_filter: Optional[str],
    year_filter: Optional[int],
) -> None:
    print("\n" + "=" * 70)
    print("PART C - Aggregate MFE/MAE stability (cell x year)")
    print("=" * 70)

    cells = sorted(df["cell"].dropna().unique())
    if cell_filter:
        cells = [c for c in cells if c == cell_filter]

    years = sorted(df["year"].dropna().unique())
    if year_filter:
        years = [y for y in years if y == year_filter]

    for cell in cells:
        cdf = df[df["cell"] == cell]
        print(f"\n--- {cell.upper()} ---")

        header = (
            f"  {'Year':>5}  {'n':>5}  "
            f"{'W_MFE':>7}  {'W_MAE':>7}  {'L_MFE':>7}  {'L_MAE':>7}  "
            f"{'W_MFE1%':>8}  {'L_MFE1%':>8}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))

        for year in years:
            ydf = cdf[cdf["year"] == year]
            if ydf.empty:
                continue

            wins = ydf[ydf["is_win"]]
            losses = ydf[~ydf["is_win"]]

            w_mfe = wins["mfe_atr"].median()
            w_mae = wins["mae_atr"].median()
            l_mfe = losses["mfe_atr"].median()
            l_mae = losses["mae_atr"].median()
            w_mfe1 = _pct(wins["first_extreme"], "MFE_FIRST")
            l_mfe1 = _pct(losses["first_extreme"], "MFE_FIRST")

            def _f(v: float) -> str:
                return f"{v:>7.3f}" if not np.isnan(v) else "    n/a"

            print(
                f"  {int(year):>5}  {len(ydf):>5}  "
                f"{_f(w_mfe)}  {_f(w_mae)}  {_f(l_mfe)}  {_f(l_mae)}  "
                f"{w_mfe1:>7.1f}%  {l_mfe1:>7.1f}%"
            )


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Trade quality inspection report.")
    parser.add_argument("--cell", type=str, default=None, help="Filter to one cell, e.g. jpy|bear")
    parser.add_argument("--year", type=int, default=None, help="Filter to one year, e.g. 2021")
    args = parser.parse_args()

    cell_filter: Optional[str] = args.cell.lower() if args.cell else None
    year_filter: Optional[int] = args.year

    logger.info("Loading data from DB...")
    df = load_data()
    logger.info("Loaded %d rows across %d signals.", len(df), df["signal_id"].nunique())

    print_part_a(df, cell_filter)
    print_part_b(df, cell_filter, year_filter)
    print_part_c(df, cell_filter, year_filter)

    logger.info("Done.")


if __name__ == "__main__":
    main()

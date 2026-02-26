#!/usr/bin/env python3
"""
trade_explorer.py — Qualitative analysis of individual trade outcomes.

Examines signal-time context for wins vs losses. Output is for human inspection,
NOT algorithmic gate discovery. Use this to form hypotheses, then verify them
logically before encoding as gates.

Modes:
  divergence  Per-cell feature divergence ranking (median wins vs median losses).
              Reveals which features DIFFER most between outcomes — not which to gate on.
  samples     Print N individual trade examples with full signal-time context.
  regime      Year-by-year win rate per cell across all SL models.

Usage:
  python analysis/trade_explorer.py --mode divergence
  python analysis/trade_explorer.py --mode divergence --cell jpy|bear
  python analysis/trade_explorer.py --mode divergence --cell jpy|bear --sl SL_ATR_0_5
  python analysis/trade_explorer.py --mode samples --cell jpy|bear --n 5
  python analysis/trade_explorer.py --mode samples --cell jpy|bear --outcome tp --n 10
  python analysis/trade_explorer.py --mode samples --cell jpy|bear --outcome sl --n 10
  python analysis/trade_explorer.py --mode regime
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

# ── Symbol → Group ─────────────────────────────────────────────────────────────
_S2G: dict[str, str] = {}
for _g, _syms in {
    "jpy":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "comm": ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}.items():
    for _s in _syms:
        _S2G[_s] = _g

# ── Feature columns (all signal-time, no outcome data) ─────────────────────────
# Grouped by origin for readability.
FEATURE_COLS: list[str] = [
    # entry_signal
    "trend_alignment_strength",         # 1–3: how many TFs align
    "hour_of_day_utc",                  # 0–23
    "aoi_touch_count_since_creation",   # prior touches of this AOI
    "max_retest_penetration_atr",       # how deep the retest went into AOI
    "bars_between_retest_and_break",    # gap between retest and break candle
    "no_conflict",                      # 1 = no conflicted TF (derived)
    # pre_entry_context_v2 — location
    "htf_range_position_mid",           # 0=bottom 1=top of daily range
    "htf_range_position_high",          # same for weekly range
    "aoi_midpoint_range_position_mid",  # where the AOI sits in daily range
    "htf_range_size_mid_atr",           # daily range width in ATR (compressed/expanded)
    # pre_entry_context_v2 — momentum/regime
    "session_directional_bias",         # current session momentum (direction-aware, signed)
    "recent_trend_payoff_atr_24h",      # price moved in our direction last 24h
    "recent_trend_payoff_atr_48h",      # price moved in our direction last 48h
    "trend_age_bars_1h",                # how long the trend has been aligned
    "trend_age_impulses",               # impulse count in trend
    # pre_entry_context_v2 — space / obstacles
    "distance_to_next_htf_obstacle_atr",  # room to target
    "distance_from_last_impulse_atr",     # how far we've moved since last impulse
    "distance_to_mid_tf_high_atr",        # distance to daily high
    "distance_to_mid_tf_low_atr",         # distance to daily low
    "distance_to_prev_session_high_atr",  # distance to prev session high
    "distance_to_prev_session_low_atr",   # distance to prev session low
    # pre_entry_context_v2 — AOI quality
    "aoi_height_atr",                   # zone tightness (smaller = more precise)
    "aoi_time_since_last_touch",        # bars since last AOI touch
    "aoi_last_reaction_strength",       # how strongly price reacted from AOI before
    # pre_entry_context_v2 — break/retest candle
    "break_impulse_range_atr",          # break candle total size
    "break_impulse_body_atr",           # break candle body size
    "break_close_location",             # where break candle closed in its range (conviction)
    "retest_candle_body_penetration",   # how cleanly the retest candle penetrated AOI
    # sl_geometry_unbiased — signal candle
    "opp_extreme",                      # opposing wick of signal candle in ATR
    "signal_candle_range_atr",          # signal candle total range
    "signal_candle_body_atr",           # signal candle body
    "aoi_near_edge_atr",                # SL distance (near edge)
    "aoi_far_edge_atr",                 # SL distance (far edge)
]

# Human-readable notes: expected direction of effect for wins ("+": higher is better, "-": lower)
# Used purely for annotation, not for any computation.
_EXPECTED_DIRECTION: dict[str, str] = {
    "trend_alignment_strength": "+",
    "aoi_touch_count_since_creation": "-",  # fresher AOI = fewer touches
    "max_retest_penetration_atr": "?",
    "bars_between_retest_and_break": "?",
    "no_conflict": "+",
    "htf_range_position_mid": "?",          # depends on direction: bears want high, bulls low
    "session_directional_bias": "+",        # direction-aware, positive = aligned
    "recent_trend_payoff_atr_24h": "+",     # trend working recently
    "recent_trend_payoff_atr_48h": "+",
    "distance_to_next_htf_obstacle_atr": "+",  # more room = better
    "distance_from_last_impulse_atr": "-",  # closer to last impulse = fresher
    "aoi_height_atr": "-",                  # tighter zone = better
    "aoi_last_reaction_strength": "+",      # stronger prior reaction = better AOI
    "break_impulse_range_atr": "+",         # stronger break = better
    "break_close_location": "+",            # close high in range = conviction
    "opp_extreme": "-",                     # less opposing wick = cleaner candle
}

# ── SQL ────────────────────────────────────────────────────────────────────────
_QUERY = """
SELECT
    es.id,
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
    pec.distance_to_mid_tf_high_atr,
    pec.distance_to_mid_tf_low_atr,
    pec.distance_to_prev_session_high_atr,
    pec.distance_to_prev_session_low_atr,
    sg.signal_candle_opposite_extreme_atr AS opp_extreme,
    sg.signal_candle_range_atr,
    sg.signal_candle_body_atr,
    sg.aoi_near_edge_atr,
    sg.aoi_far_edge_atr,
    esi.sl_model,
    esi.exit_reason,
    esi.return_r
FROM trenda_replay.entry_signal              es
JOIN trenda_replay.pre_entry_context_v2      pec ON pec.entry_signal_id = es.id
JOIN trenda_replay.sl_geometry_unbiased      sg  ON sg.entry_signal_id  = es.id
JOIN trenda_replay.exit_simulation_unbiased  esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
  AND esi.rr_multiple         = 2.0
ORDER BY es.signal_time
"""


def load_data() -> pd.DataFrame:
    conn = psycopg2.connect(**POSTGRES_DB)
    try:
        cur = conn.cursor()
        cur.execute(_QUERY)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(rows, columns=cols)
    finally:
        conn.close()

    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"] = df["signal_time"].dt.year
    df["group"] = df["symbol"].map(_S2G)
    df["cell"] = df["group"] + "|" + df["direction"].str[:4]   # e.g. jpy|bear
    # NUMERIC columns come back as decimal.Decimal — cast all to float
    for col in df.columns:
        if col not in ("id", "symbol", "direction", "conflicted_tf", "sl_model", "exit_reason"):
            df[col] = pd.to_numeric(df[col], errors="ignore")

    df["win"] = (df["exit_reason"] == "TP").astype(int)
    df["no_conflict"] = df["conflicted_tf"].isna().astype(float)
    df = df.dropna(subset=["group", "cell"])
    return df


def _robust_effect(wins: pd.Series, losses: pd.Series) -> float:
    """Robust effect size: (median_win - median_loss) / pooled_IQR.
    Positive = feature is higher for wins. Range roughly ±2 for typical data."""
    mw = wins.median()
    ml = losses.median()
    iqr_w = wins.quantile(0.75) - wins.quantile(0.25)
    iqr_l = losses.quantile(0.75) - losses.quantile(0.25)
    pooled_iqr = (iqr_w + iqr_l) / 2.0
    if pooled_iqr < 1e-9:
        return 0.0
    return float((mw - ml) / pooled_iqr)


def mode_divergence(df: pd.DataFrame, cell_filter: Optional[str], sl_filter: Optional[str]) -> None:
    """Per-cell feature divergence: which features differ most between wins and losses."""
    cells = sorted(df["cell"].unique())
    if cell_filter:
        cells = [c for c in cells if c == cell_filter]
        if not cells:
            logger.error("Cell '%s' not found. Available: %s", cell_filter, sorted(df["cell"].unique()))
            return

    for cell in cells:
        sub = df[df["cell"] == cell].copy()
        if sl_filter:
            sub = sub[sub["sl_model"] == sl_filter]

        if sub.empty:
            continue

        wins = sub[sub["win"] == 1]
        losses = sub[sub["win"] == 0]
        n_w, n_l = len(wins), len(losses)

        if n_w < 5 or n_l < 5:
            continue

        wr = 100.0 * n_w / len(sub)
        sl_note = f"  sl={sl_filter}" if sl_filter else ""
        print(f"\n{'='*72}")
        print(f"  {cell.upper():<12}  n={len(sub):>4}  wins={n_w:>4}  losses={n_l:>4}  win%={wr:.1f}%{sl_note}")
        print(f"{'='*72}")
        print(f"  {'Feature':<44} {'exp_dir':>7} {'med_win':>8} {'med_los':>8} {'effect':>7}")
        print(f"  {'-'*44} {'-'*7} {'-'*8} {'-'*8} {'-'*7}")

        rows: list[tuple[str, str, float, float, float]] = []
        for col in FEATURE_COLS:
            if col not in sub.columns:
                continue
            w_vals = wins[col].dropna()
            l_vals = losses[col].dropna()
            if len(w_vals) < 5 or len(l_vals) < 5:
                continue
            effect = _robust_effect(w_vals, l_vals)
            exp = _EXPECTED_DIRECTION.get(col, "?")
            rows.append((col, exp, float(w_vals.median()), float(l_vals.median()), effect))

        rows.sort(key=lambda r: abs(r[4]), reverse=True)

        for col, exp, mw, ml, eff in rows:
            # Flag if effect contradicts expected direction
            contradiction = ""
            if exp == "+" and eff < -0.2:
                contradiction = " !"
            elif exp == "-" and eff > 0.2:
                contradiction = " !"
            marker = " <<" if abs(eff) > 0.30 else ""
            print(f"  {col:<44} {exp:>7} {mw:>8.3f} {ml:>8.3f} {eff:>+7.3f}{marker}{contradiction}")


def mode_samples(
    df: pd.DataFrame,
    cell_filter: Optional[str],
    sl_filter: Optional[str],
    outcome: Optional[str],
    n: int,
) -> None:
    """Print N individual trades with all signal-time context."""
    sub = df.copy()
    if cell_filter:
        sub = sub[sub["cell"] == cell_filter]
    if sl_filter:
        sub = sub[sub["sl_model"] == sl_filter]
    if outcome == "tp":
        sub = sub[sub["win"] == 1]
    elif outcome == "sl":
        sub = sub[sub["win"] == 0]

    if sub.empty:
        logger.error("No trades matched the given filters.")
        return

    sample = sub.sample(min(n, len(sub)), random_state=42)
    # Sort: wins first (highest return), then losses (most negative)
    sample = sample.sort_values("return_r", ascending=False)

    for _, row in sample.iterrows():
        outcome_tag = f"TP  +{row['return_r']:.2f}R" if row["win"] else f"SL   {row['return_r']:.2f}R"
        conflict = row["conflicted_tf"] if pd.notna(row["conflicted_tf"]) else "none"
        print(f"\n{'─'*68}")
        print(f"  [{outcome_tag}]  {row['cell'].upper():<10}  {row['symbol']:<8}  {row['sl_model']}")
        print(f"  {str(row['signal_time'])[:16]}  year={int(row['year'])}  hour={int(row['hour_of_day_utc']):02d}UTC  conflict={conflict}")
        print(f"  {'─'*66}")

        for col in FEATURE_COLS:
            if col not in row.index:
                continue
            val = row[col]
            if pd.isna(val):
                print(f"  {col:<44}  {'NULL':>10}")
            else:
                print(f"  {col:<44}  {float(val):>10.4f}")


def mode_regime(df: pd.DataFrame, cell_filter: Optional[str], sl_filter: Optional[str]) -> None:
    """Year-by-year win rate per cell."""
    sub = df.copy()
    if sl_filter:
        sub = sub[sub["sl_model"] == sl_filter]

    cells = sorted(sub["cell"].unique())
    if cell_filter:
        cells = [c for c in cells if c == cell_filter]

    years = sorted(sub["year"].unique())

    # Header
    col_w = 9
    print(f"\n  {'Cell':<15}" + "".join(f"{y:>{col_w}}" for y in years) + f"  {'ALL':>{col_w}}")
    print("  " + "-" * (15 + col_w * len(years) + col_w + 2))

    for cell in cells:
        c_sub = sub[sub["cell"] == cell]
        row_str = f"  {cell:<15}"
        for y in years:
            yr = c_sub[c_sub["year"] == y]
            if len(yr) == 0:
                row_str += f"  {'—':>{col_w - 2}}"
            else:
                wr = 100.0 * yr["win"].mean()
                row_str += f"  {wr:>4.1f}%({len(yr):>3})"
        wr_all = 100.0 * c_sub["win"].mean() if len(c_sub) > 0 else 0.0
        row_str += f"  {wr_all:>5.1f}%"
        print(row_str)


def main() -> None:
    parser = argparse.ArgumentParser(description="Qualitative trade outcome explorer.")
    parser.add_argument(
        "--mode",
        choices=["divergence", "samples", "regime"],
        default="divergence",
        help="Analysis mode.",
    )
    parser.add_argument("--cell", default=None, help="Filter by cell, e.g. 'jpy|bear'.")
    parser.add_argument("--sl", default=None, dest="sl_model", help="Filter by SL model, e.g. 'SL_ATR_0_5'.")
    parser.add_argument(
        "--outcome",
        choices=["tp", "sl"],
        default=None,
        help="Filter by outcome (samples mode only).",
    )
    parser.add_argument("--n", type=int, default=10, help="Number of samples (samples mode).")
    args = parser.parse_args()

    logger.info("Loading trades from DB...")
    df = load_data()
    logger.info(
        "Loaded %d rows — %d cells, years %s–%s",
        len(df),
        df["cell"].nunique(),
        df["year"].min(),
        df["year"].max(),
    )

    if args.mode == "divergence":
        mode_divergence(df, args.cell, args.sl_model)
    elif args.mode == "samples":
        mode_samples(df, args.cell, args.sl_model, args.outcome, args.n)
    elif args.mode == "regime":
        mode_regime(df, args.cell, args.sl_model)


if __name__ == "__main__":
    main()

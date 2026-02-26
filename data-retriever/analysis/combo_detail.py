#!/usr/bin/env python3
"""
combo_detail.py — Per-fold LOO detail for the two [+] depth-2 gate combos.

  comm|bearish: htf_range_position_high (mostly_up)  + break_close_location (mostly_down)
  jpy|bullish:  aoi_last_reaction_strength (mostly_down) + htf_range_position_high (mostly_down)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
import psycopg2

from configuration.db_config import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

ALL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
RR        = 2.0
BREAKEVEN = 100.0 / (1.0 + RR)

COMBOS: list[tuple[str, str, str, str, str]] = [
    ("comm|bearish", "htf_range_position_high",    "mostly_up",   "break_close_location",     "mostly_down"),
    ("jpy|bullish",  "aoi_last_reaction_strength",  "mostly_down", "htf_range_position_high",  "mostly_down"),
]

GROUPS: dict[str, list[str]] = {
    "jpy":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "comm": ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}
_S2G = {s: g for g, ss in GROUPS.items() for s in ss}

_SQL = """\
SELECT
    es.id, es.signal_time, es.symbol, es.direction,
    es.trend_alignment_strength, es.hour_of_day_utc,
    es.aoi_touch_count_since_creation,
    es.max_retest_penetration_atr, es.bars_between_retest_and_break,
    es.conflicted_tf,
    pec.htf_range_position_mid, pec.htf_range_position_high,
    pec.session_directional_bias,
    pec.break_close_location, pec.break_impulse_range_atr,
    pec.break_impulse_body_atr, pec.retest_candle_body_penetration,
    pec.aoi_height_atr, pec.distance_to_next_htf_obstacle_atr,
    pec.distance_from_last_impulse_atr,
    pec.recent_trend_payoff_atr_24h, pec.recent_trend_payoff_atr_48h,
    pec.aoi_time_since_last_touch, pec.aoi_last_reaction_strength,
    pec.htf_range_size_mid_atr,
    pec.aoi_midpoint_range_position_mid,
    pec.trend_age_bars_1h, pec.trend_age_impulses,
    sg.signal_candle_opposite_extreme_atr AS opp_extreme,
    sg.signal_candle_range_atr, sg.signal_candle_body_atr,
    sg.aoi_near_edge_atr, sg.aoi_far_edge_atr,
    esi.sl_model, esi.exit_reason, esi.return_r
FROM trenda_replay.entry_signal          es
JOIN trenda_replay.pre_entry_context_v2  pec ON pec.entry_signal_id = es.id
JOIN trenda_replay.sl_geometry_unbiased  sg  ON sg.entry_signal_id  = es.id
JOIN trenda_replay.exit_simulation_unbiased esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
  AND esi.rr_multiple         = 2.0
ORDER BY es.signal_time
"""


def load_data() -> pd.DataFrame:
    cfg = {k: v for k, v in POSTGRES_DB.items() if k != "options"}
    cfg["options"] = "-c search_path=trenda_replay,public"
    logger.info("Loading data ...")
    with psycopg2.connect(**cfg) as conn:
        df = pd.read_sql_query(_SQL, conn)
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"]        = df["signal_time"].dt.year
    df["group"]       = df["symbol"].map(_S2G)
    df["win"]         = (df["exit_reason"] == "TP").astype(int)
    df = df[df["group"].notna()].copy()
    df["cell"]        = df["group"] + "|" + df["direction"]
    df = df[df["sl_model"] != "SL_AOI_NEAR"].copy()
    logger.info("Loaded %d rows after SL_AOI_NEAR exclusion", len(df))
    return df


def _exp(win_pct: float) -> float:
    w = win_pct / 100.0
    return round(w * RR - (1.0 - w), 4)


def loo_single(cell_df: pd.DataFrame, p: str, d: str) -> list[dict]:
    sub      = cell_df[cell_df[p].notna()].copy()
    keep_top = d in {"consistent_up", "mostly_up"}
    folds    = []
    for yr in ALL_YEARS:
        train = sub[sub["year"] != yr]
        test  = sub[sub["year"] == yr]
        if len(train) < 20 or len(test) < 5:
            continue
        thr   = train[p].median()
        gated = test[test[p] > thr] if keep_top else test[test[p] <= thr]
        n = len(gated)
        if n == 0:
            continue
        win = 100.0 * gated["win"].mean()
        folds.append({"year": yr, "n": n, "win": round(win, 1), "exp": _exp(win), "thr": round(thr, 4)})
    return folds


def loo_combo(cell_df: pd.DataFrame, p1: str, d1: str, p2: str, d2: str) -> list[dict]:
    sub  = cell_df[cell_df[p1].notna() & cell_df[p2].notna()].copy()
    kt1  = d1 in {"consistent_up", "mostly_up"}
    kt2  = d2 in {"consistent_up", "mostly_up"}
    folds = []
    for yr in ALL_YEARS:
        train = sub[sub["year"] != yr]
        test  = sub[sub["year"] == yr]
        if len(train) < 20 or len(test) < 5:
            continue
        t1 = train[p1].median()
        t2 = train[p2].median()
        g  = test[test[p1] > t1] if kt1 else test[test[p1] <= t1]
        g  = g[g[p2] > t2]       if kt2 else g[g[p2] <= t2]
        n  = len(g)
        if n == 0:
            continue
        win = 100.0 * g["win"].mean()
        folds.append({
            "year": yr, "n": n, "win": round(win, 1), "exp": _exp(win),
            "thr_p1": round(t1, 4), "thr_p2": round(t2, 4),
        })
    return folds


def _print_folds(folds: list[dict], headers: list[str]) -> None:
    h = "  " + "  ".join(f"{hdr:>10}" for hdr in headers)
    print(h)
    print("  " + "-" * (len(h) - 2))
    for f in folds:
        marker = " <BE" if f["win"] <= BREAKEVEN else ""
        vals   = [str(f.get(k, "—")) for k in ["year", "n", "win", "exp"] + [k for k in f if k.startswith("thr")]]
        print("  " + "  ".join(f"{v:>10}" for v in vals) + marker)


def _summary(folds: list[dict], base_win: float) -> None:
    wins = [f["win"] for f in folds]
    exps = [f["exp"] for f in folds]
    ns   = [f["n"]   for f in folds]
    print(
        f"  avg_n={np.mean(ns):.0f}  avg_win={np.mean(wins):.1f}%  "
        f"avg_exp={np.mean(exps):.4f}  "
        f"above_BE={sum(1 for w in wins if w > BREAKEVEN)}/{len(folds)}  "
        f"exp+={sum(1 for e in exps if e > 0)}/{len(folds)}  "
        f"vs_base={np.mean(wins) - base_win:+.1f}pp"
    )


def main() -> None:
    df = load_data()

    for (cell, p1, d1, p2, d2) in COMBOS:
        cell_df  = df[df["cell"] == cell]
        base_win = 100.0 * cell_df["win"].mean()

        s1  = loo_single(cell_df, p1, d1)
        s2  = loo_single(cell_df, p2, d2)
        cmb = loo_combo(cell_df, p1, d1, p2, d2)

        print(f"\n{'='*72}")
        print(f"  CELL: {cell}  |  baseline n={len(cell_df)}  win={base_win:.1f}%  exp={_exp(base_win)}")
        print(f"{'='*72}")

        print(f"\n  -- Single gate 1: {p1} [{d1}]")
        _summary(s1, base_win)
        _print_folds(s1, ["year", "n", "win", "exp", "thr_p1"])

        print(f"\n  -- Single gate 2: {p2} [{d2}]")
        _summary(s2, base_win)
        _print_folds(s2, ["year", "n", "win", "exp", "thr_p2"])

        print(f"\n  -- COMBINED: {p1} [{d1}]  +  {p2} [{d2}]")
        _summary(cmb, base_win)
        _print_folds(cmb, ["year", "n", "win", "exp", "thr_p1", "thr_p2"])


if __name__ == "__main__":
    main()

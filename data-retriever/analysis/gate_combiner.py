#!/usr/bin/env python3
"""
gate_combiner.py — Depth-2 gate combination for the 3 strong single-gate candidates.

For each strong cell, pairs the primary gate with every other 6/7 candidate
from the same cell and runs 7-fold LOO on the combined gate.

Strong primaries (from gate_validator.py results):
  comm|bearish  → htf_range_position_high  (mostly_up,   5/7 above BE)
  jpy|bullish   → aoi_last_reaction_strength (mostly_down, 5/7 above BE)
  usd|bullish   → aoi_time_since_last_touch  (mostly_up,   5/7 above BE)
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

# Primary gates to anchor each cell
PRIMARIES: list[tuple[str, str, str]] = [
    ("comm|bearish", "htf_range_position_high",    "mostly_up"),
    ("jpy|bullish",  "aoi_last_reaction_strength",  "mostly_down"),
    ("usd|bullish",  "aoi_time_since_last_touch",   "mostly_up"),
]

# Min thresholds for secondary candidates to pair
MIN_STABILITY = 6
MIN_LIFT_PP   = 2.0

_BINARY_PARAMS = {"conflicted_tf"}

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


def load_candidates() -> pd.DataFrame:
    csv_path = Path(__file__).parent / "correlation_stability.csv"
    cands = pd.read_csv(csv_path)
    return cands[
        (cands["stability_score"] >= MIN_STABILITY)
        & (cands["avg_lift_pp"] >= MIN_LIFT_PP)
        & (cands["direction"] != "mixed")
    ].copy()


def _expectancy(win_pct: float) -> float:
    w = win_pct / 100.0
    return round(w * RR - (1.0 - w), 4)


def _apply_gate(df: pd.DataFrame, param: str, direction: str, threshold: float | str) -> pd.DataFrame:
    keep_top = direction in {"consistent_up", "mostly_up"}
    if param in _BINARY_PARAMS:
        return df[df[param].isna()] if keep_top else df[df[param].notna()]
    if keep_top:
        return df[df[param] > threshold]  # type: ignore[operator]
    return df[df[param] <= threshold]     # type: ignore[operator]


def _train_threshold(train: pd.DataFrame, param: str, direction: str) -> float | str:
    if param in _BINARY_PARAMS:
        return "binary"
    return train[param].median()


def loo_single(
    cell_df: pd.DataFrame,
    param: str,
    direction: str,
) -> list[dict]:
    sub = cell_df[cell_df[param].notna()] if param not in _BINARY_PARAMS else cell_df
    folds = []
    for yr in ALL_YEARS:
        train = sub[sub["year"] != yr]
        test  = sub[sub["year"] == yr]
        if len(train) < 20 or len(test) < 5:
            continue
        thr   = _train_threshold(train, param, direction)
        gated = _apply_gate(test, param, direction, thr)
        n = len(gated)
        if n == 0:
            continue
        win = 100.0 * gated["win"].mean()
        folds.append({"year": yr, "n": n, "win": round(win, 1), "exp": _expectancy(win)})
    return folds


def loo_combined(
    cell_df: pd.DataFrame,
    p1: str, d1: str,
    p2: str, d2: str,
) -> list[dict]:
    """LOO with both gates applied; train median derived from train set for each param."""
    params_numeric = [p for p in (p1, p2) if p not in _BINARY_PARAMS]
    sub = cell_df.copy()
    for p in params_numeric:
        sub = sub[sub[p].notna()]

    folds = []
    for yr in ALL_YEARS:
        train = sub[sub["year"] != yr]
        test  = sub[sub["year"] == yr]
        if len(train) < 20 or len(test) < 5:
            continue

        thr1  = _train_threshold(train, p1, d1)
        thr2  = _train_threshold(train, p2, d2)

        gated = _apply_gate(test, p1, d1, thr1)
        gated = _apply_gate(gated, p2, d2, thr2)

        n = len(gated)
        if n == 0:
            continue
        win = 100.0 * gated["win"].mean()
        folds.append({"year": yr, "n": n, "win": round(win, 1), "exp": _expectancy(win)})
    return folds


def _summarise(folds: list[dict], baseline_win: float) -> dict:
    if not folds:
        return {"n_folds": 0, "avg_n": 0, "avg_win": 0.0, "avg_exp": 0.0,
                "above_be": 0, "exp_pos": 0, "vs_base": 0.0}
    wins = [f["win"] for f in folds]
    exps = [f["exp"] for f in folds]
    ns   = [f["n"]   for f in folds]
    return {
        "n_folds":  len(folds),
        "avg_n":    round(float(np.mean(ns)), 0),
        "avg_win":  round(float(np.mean(wins)), 1),
        "avg_exp":  round(float(np.mean(exps)), 4),
        "above_be": sum(1 for w in wins if w > BREAKEVEN),
        "exp_pos":  sum(1 for e in exps if e > 0),
        "vs_base":  round(float(np.mean(wins)) - baseline_win, 1),
    }


def main() -> None:
    df         = load_data()
    candidates = load_candidates()

    rows: list[dict] = []

    for (cell, p1, d1) in PRIMARIES:
        cell_df      = df[df["cell"] == cell]
        baseline_win = 100.0 * cell_df["win"].mean()

        single_folds = loo_single(cell_df, p1, d1)
        single_s     = _summarise(single_folds, baseline_win)

        # Secondaries: same cell, different param, direction != mixed
        secondaries = candidates[
            (candidates["cell"] == cell)
            & (candidates["param"] != p1)
        ][["param", "direction"]].values.tolist()

        print(f"\n{'='*76}")
        print(
            f"  CELL: {cell}  |  baseline win={baseline_win:.1f}%"
            f"  |  PRIMARY: {p1} [{d1}]"
        )
        print(
            f"  Single-gate LOO: avg_n={single_s['avg_n']}  "
            f"avg_win={single_s['avg_win']}%  avg_exp={single_s['avg_exp']}  "
            f"above_BE={single_s['above_be']}/{single_s['n_folds']}  "
            f"vs_base={single_s['vs_base']:+}pp"
        )
        print(f"{'='*76}")
        print(
            f"  {'SECONDARY PARAM':<40} {'DIR':<14} "
            f"{'AVG_N':>6}  {'AVG_WIN':>7}  {'AVG_EXP':>8}  "
            f"{'ABE':>3}  {'EXP+':>4}  {'VS_SINGLE':>9}"
        )
        print(f"  {'-'*40} {'-'*14} {'-'*6}  {'-'*7}  {'-'*8}  {'-'*3}  {'-'*4}  {'-'*9}")

        cell_rows: list[dict] = []
        for (p2, d2) in secondaries:
            combo_folds = loo_combined(cell_df, p1, d1, p2, d2)
            combo_s     = _summarise(combo_folds, baseline_win)

            vs_single = round(combo_s["avg_win"] - single_s["avg_win"], 1)
            flag = ""
            if combo_s["above_be"] >= single_s["above_be"] and vs_single >= 0:
                flag = " [+]"
            elif combo_s["above_be"] < single_s["above_be"] - 1:
                flag = " [-]"

            print(
                f"  {p2:<40} {d2:<14} "
                f"{combo_s['avg_n']:>6.0f}  {combo_s['avg_win']:>6.1f}%  "
                f"{combo_s['avg_exp']:>8.4f}  "
                f"{combo_s['above_be']:>3}/{combo_s['n_folds']:<1}  "
                f"{combo_s['exp_pos']:>4}/{combo_s['n_folds']:<1}  "
                f"{vs_single:>+8.1f}pp{flag}"
            )

            cell_rows.append({
                "cell":         cell,
                "p1":           p1, "d1": d1,
                "p2":           p2, "d2": d2,
                "single_avg_win":  single_s["avg_win"],
                "single_avg_exp":  single_s["avg_exp"],
                "single_above_be": single_s["above_be"],
                "combo_avg_n":     combo_s["avg_n"],
                "combo_avg_win":   combo_s["avg_win"],
                "combo_avg_exp":   combo_s["avg_exp"],
                "combo_above_be":  combo_s["above_be"],
                "combo_exp_pos":   combo_s["exp_pos"],
                "vs_single_pp":    vs_single,
            })

        rows.extend(cell_rows)

    out = pd.DataFrame(rows)
    out_path = Path(__file__).parent / "gate_combinations.csv"
    out.to_csv(out_path, index=False)
    logger.info("Saved %d rows to %s", len(out), out_path)


if __name__ == "__main__":
    main()

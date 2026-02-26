#!/usr/bin/env python3
"""
gate_validator.py — LOO gate validation for correlation_stability candidates.

For each [*] / [**] candidate (cell x param x direction):
  - 7-fold LOO: train median set on 6 years, applied to held-out year.
  - Reports per-fold n / win% / expectancy, plus pass-rate summary.
  - Compares against ungated cell baseline.
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

ALL_YEARS  = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
RR         = 2.0
BREAKEVEN  = 100.0 / (1.0 + RR)   # 33.33%

# Candidate filter thresholds (mirrors brief interpretation flags)
MIN_STABILITY  = 6
MIN_LIFT_PP    = 2.0
EXCLUDE_DIRS   = {"mixed"}

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
    mask = (
        (cands["stability_score"] >= MIN_STABILITY)
        & (cands["avg_lift_pp"]   >= MIN_LIFT_PP)
        & (~cands["direction"].isin(EXCLUDE_DIRS))
    )
    result = cands[mask].copy()
    logger.info("Loaded %d candidates from correlation_stability.csv", len(result))
    return result


def _expectancy(win_pct: float, rr: float = RR) -> float:
    w = win_pct / 100.0
    return round(w * rr - (1.0 - w), 4)


def _cell_baseline(cell_df: pd.DataFrame) -> dict:
    n   = len(cell_df)
    win = 100.0 * cell_df["win"].mean() if n > 0 else 0.0
    return {"n": n, "win": round(win, 1), "exp": _expectancy(win)}


_BINARY_PARAMS = {"conflicted_tf"}


def validate_candidate(
    df: pd.DataFrame,
    cell: str,
    param: str,
    direction: str,
) -> list[dict]:
    """
    7-fold LOO: for each held-out year, compute train median on remaining 6 years,
    apply gate to held-out year, return per-fold metrics.
    Binary params (conflicted_tf): gate on NULL vs not-NULL; threshold shown as "binary".
    """
    cell_df  = df[df["cell"] == cell].copy()
    is_binary = param in _BINARY_PARAMS
    # For numeric params, drop rows where param is null
    if not is_binary:
        cell_df = cell_df[cell_df[param].notna()]

    keep_top  = direction in {"consistent_up", "mostly_up"}

    folds: list[dict] = []
    for holdout_yr in ALL_YEARS:
        train = cell_df[cell_df["year"] != holdout_yr]
        test  = cell_df[cell_df["year"] == holdout_yr]

        if len(train) < 20 or len(test) < 5:
            continue

        if is_binary:
            # keep_top (direction=up) = no-conflict (NULL) is better → keep NULL
            # keep_down = conflict is better → keep not-NULL
            if keep_top:
                gated = test[test[param].isna()]
            else:
                gated = test[test[param].notna()]
            threshold_label = "NULL" if keep_top else "NOT_NULL"
        else:
            threshold = train[param].median()
            if keep_top:
                gated = test[test[param] > threshold]
            else:
                gated = test[test[param] <= threshold]
            threshold_label = str(round(threshold, 4))

        n = len(gated)
        if n == 0:
            continue

        win = 100.0 * gated["win"].mean()
        folds.append({
            "year":      holdout_yr,
            "n":         n,
            "win":       round(win, 1),
            "exp":       _expectancy(win),
            "threshold": threshold_label,
        })

    return folds


def summarise(folds: list[dict], baseline_win: float) -> dict:
    if not folds:
        return {}
    wins  = [f["win"] for f in folds]
    exps  = [f["exp"] for f in folds]
    ns    = [f["n"]   for f in folds]
    return {
        "n_folds":          len(folds),
        "avg_n_per_fold":   round(float(np.mean(ns)), 1),
        "avg_win":          round(float(np.mean(wins)), 1),
        "avg_exp":          round(float(np.mean(exps)), 4),
        "folds_above_be":   sum(1 for w in wins if w > BREAKEVEN),
        "folds_exp_pos":    sum(1 for e in exps if e > 0),
        "vs_baseline_pp":   round(float(np.mean(wins)) - baseline_win, 1),
    }


def _print_candidate(
    cell: str,
    param: str,
    direction: str,
    stability: int,
    avg_lift: float,
    folds: list[dict],
    summary: dict,
    baseline: dict,
) -> None:
    flag = "[**]" if stability == 7 and avg_lift >= 3 else "[*] "
    print(f"\n{'-'*72}")
    print(
        f"  {flag} {cell}  |  {param}  |  {direction}  "
        f"|  stab={stability}/7  lift={avg_lift}pp"
    )
    print(f"  Baseline: n={baseline['n']}  win={baseline['win']}%  exp={baseline['exp']}")
    print(
        f"  LOO summary: avg_n={summary.get('avg_n_per_fold','—')}  "
        f"avg_win={summary.get('avg_win','—')}%  "
        f"avg_exp={summary.get('avg_exp','—')}  "
        f"above_BE={summary.get('folds_above_be','—')}/{summary.get('n_folds','—')}  "
        f"exp+={summary.get('folds_exp_pos','—')}/{summary.get('n_folds','—')}  "
        f"vs_base={summary.get('vs_baseline_pp','—'):+}pp"
    )
    if folds:
        print(f"  {'Year':<6} {'N':>5}  {'Win%':>6}  {'Exp':>7}  {'Threshold':>10}")
        for f in folds:
            marker = " <BE" if f["win"] <= BREAKEVEN else ""
            print(
                f"  {f['year']:<6} {f['n']:>5}  {f['win']:>5.1f}%  "
                f"{f['exp']:>7.4f}  {str(f['threshold']):>10}{marker}"
            )


def main() -> None:
    df         = load_data()
    candidates = load_candidates()

    rows: list[dict] = []

    cells = sorted(candidates["cell"].unique())
    for cell in cells:
        cell_df    = df[df["cell"] == cell]
        baseline   = _cell_baseline(cell_df)
        cell_cands = candidates[candidates["cell"] == cell].sort_values(
            ["stability_score", "avg_lift_pp"], ascending=[False, False]
        )

        print(f"\n{'='*72}")
        print(f"  CELL: {cell}  |  baseline n={baseline['n']}  win={baseline['win']}%  exp={baseline['exp']}")
        print(f"{'='*72}")

        for _, row in cell_cands.iterrows():
            folds   = validate_candidate(df, cell, row["param"], row["direction"])
            summary = summarise(folds, baseline["win"])

            _print_candidate(
                cell, row["param"], row["direction"],
                int(row["stability_score"]), float(row["avg_lift_pp"]),
                folds, summary, baseline,
            )

            rows.append({
                "cell":              cell,
                "param":             row["param"],
                "direction":         row["direction"],
                "stability_score":   row["stability_score"],
                "avg_lift_pp":       row["avg_lift_pp"],
                "baseline_win":      baseline["win"],
                "baseline_exp":      baseline["exp"],
                **{f"loo_{k}": v for k, v in summary.items()},
            })

    out = pd.DataFrame(rows)
    out_path = Path(__file__).parent / "gate_validation.csv"
    out.to_csv(out_path, index=False)
    logger.info("Saved %d rows to %s", len(out), out_path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
correlation_stability.py — Per-parameter directional stability analysis.

For each numeric pre-entry parameter x cell (group|direction):
  - Per year: median-split into top/bottom half, compute win% for each.
  - Stability score: years where top-half win% > bottom-half win% (or vice versa).
  - Output: ranked console table + correlation_stability.csv
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

# ── Constants ──────────────────────────────────────────────────────────────────
ALL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]

GROUPS: dict[str, list[str]] = {
    "jpy":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "comm": ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}
_S2G = {s: g for g, ss in GROUPS.items() for s in ss}

NUMERIC_PARAMS: list[str] = [
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
    "max_retest_penetration_atr",
    "bars_between_retest_and_break",
    "aoi_touch_count_since_creation",
    "signal_candle_range_atr",
    "signal_candle_body_atr",
    "aoi_near_edge_atr",
    "aoi_far_edge_atr",
    "opp_extreme",
    "trend_alignment_strength",
    "hour_of_day_utc",
]

# conflicted_tf: binary (NULL = no conflict, any value = conflict)
BINARY_PARAMS: list[str] = ["conflicted_tf"]

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
    # SL_AOI_NEAR excluded per brief (structural outlier, 23–25% win%)
    df = df[df["sl_model"] != "SL_AOI_NEAR"].copy()
    logger.info("Loaded %d rows after SL_AOI_NEAR exclusion", len(df))
    return df


def _analyse_numeric(
    df: pd.DataFrame,
    cell: str,
    param: str,
) -> dict | None:
    """Median-split stability analysis for one numeric param x cell."""
    sub = df[(df["cell"] == cell) & df[param].notna()].copy()
    if sub.empty:
        return None

    year_directions: list[int] = []  # +1 = top > bottom, -1 = top < bottom
    year_lifts: list[float] = []

    for yr in ALL_YEARS:
        yr_df = sub[sub["year"] == yr]
        if len(yr_df) < 10:
            continue

        median = yr_df[param].median()
        top    = yr_df[yr_df[param] >  median]
        bottom = yr_df[yr_df[param] <= median]

        if len(top) < 5 or len(bottom) < 5:
            continue

        win_top    = 100.0 * top["win"].mean()
        win_bottom = 100.0 * bottom["win"].mean()
        lift       = win_top - win_bottom

        if lift > 0:
            year_directions.append(1)
        elif lift < 0:
            year_directions.append(-1)
        else:
            year_directions.append(0)

        year_lifts.append(abs(lift))

    if not year_directions:
        return None

    n_years    = len(year_directions)
    up_count   = sum(1 for d in year_directions if d > 0)
    down_count = sum(1 for d in year_directions if d < 0)

    if up_count == n_years:
        direction = "consistent_up"
        stability = up_count
    elif down_count == n_years:
        direction = "consistent_down"
        stability = down_count
    elif up_count > down_count:
        direction = "mostly_up"
        stability = up_count
    elif down_count > up_count:
        direction = "mostly_down"
        stability = down_count
    else:
        direction = "mixed"
        stability = max(up_count, down_count)

    avg_lift = float(np.mean(year_lifts)) if year_lifts else 0.0

    years_detail = ",".join(
        f"{yr}:{'up' if d > 0 else 'down' if d < 0 else 'tie'}"
        for yr, d in zip(
            [y for y in ALL_YEARS if len(sub[sub["year"] == y]) >= 10],
            year_directions,
        )
    )

    return {
        "cell":            cell,
        "param":           param,
        "direction":       direction,
        "stability_score": stability,
        "n_years_tested":  n_years,
        "avg_lift_pp":     round(avg_lift, 2),
        "years_detail":    years_detail,
    }


def _analyse_binary(
    df: pd.DataFrame,
    cell: str,
    param: str,
) -> dict | None:
    """Binary param: compare win% for NULL vs non-NULL groups per year."""
    sub = df[df["cell"] == cell].copy()
    if sub.empty:
        return None

    year_directions: list[int] = []
    year_lifts: list[float] = []

    for yr in ALL_YEARS:
        yr_df = sub[sub["year"] == yr]
        if len(yr_df) < 10:
            continue

        no_conflict  = yr_df[yr_df[param].isna()]
        has_conflict = yr_df[yr_df[param].notna()]

        if len(no_conflict) < 5 or len(has_conflict) < 5:
            continue

        win_no  = 100.0 * no_conflict["win"].mean()
        win_yes = 100.0 * has_conflict["win"].mean()
        lift    = win_no - win_yes  # positive = no-conflict is better

        if lift > 0:
            year_directions.append(1)
        elif lift < 0:
            year_directions.append(-1)
        else:
            year_directions.append(0)

        year_lifts.append(abs(lift))

    if not year_directions:
        return None

    n_years    = len(year_directions)
    up_count   = sum(1 for d in year_directions if d > 0)
    down_count = sum(1 for d in year_directions if d < 0)

    if up_count == n_years:
        direction = "consistent_up"
        stability = up_count
    elif down_count == n_years:
        direction = "consistent_down"
        stability = down_count
    elif up_count > down_count:
        direction = "mostly_up"
        stability = up_count
    elif down_count > up_count:
        direction = "mostly_down"
        stability = down_count
    else:
        direction = "mixed"
        stability = max(up_count, down_count)

    avg_lift = float(np.mean(year_lifts)) if year_lifts else 0.0

    years_detail = ",".join(
        f"{yr}:{'up' if d > 0 else 'down' if d < 0 else 'tie'}"
        for yr, d in zip(
            [y for y in ALL_YEARS if len(sub[sub["year"] == y]) >= 10],
            year_directions,
        )
    )

    return {
        "cell":            cell,
        "param":           param,
        "direction":       direction,
        "stability_score": stability,
        "n_years_tested":  n_years,
        "avg_lift_pp":     round(avg_lift, 2),
        "years_detail":    years_detail,
    }


def run_analysis(df: pd.DataFrame) -> pd.DataFrame:
    cells  = sorted(df["cell"].unique())
    rows: list[dict] = []

    for cell in cells:
        for param in NUMERIC_PARAMS:
            if param not in df.columns:
                logger.warning("Column %s not found — skipping", param)
                continue
            result = _analyse_numeric(df, cell, param)
            if result:
                rows.append(result)

        for param in BINARY_PARAMS:
            if param not in df.columns:
                logger.warning("Column %s not found — skipping", param)
                continue
            result = _analyse_binary(df, cell, param)
            if result:
                rows.append(result)

    return pd.DataFrame(rows)


def _print_results(results: pd.DataFrame) -> None:
    if results.empty:
        print("No results.")
        return

    cells = sorted(results["cell"].unique())
    for cell in cells:
        cell_df = (
            results[results["cell"] == cell]
            .sort_values(["stability_score", "avg_lift_pp"], ascending=[False, False])
        )
        print(f"\n{'='*70}")
        print(f"  CELL: {cell}")
        print(f"{'='*70}")
        print(f"  {'PARAM':<42} {'DIR':<14} {'STAB':>4}  {'LIFT':>6}")
        print(f"  {'-'*42} {'-'*14} {'-'*4}  {'-'*6}")
        for _, row in cell_df.iterrows():
            flag = ""
            if row["stability_score"] == 7 and row["avg_lift_pp"] >= 3:
                flag = " [**]"
            elif (
                row["stability_score"] >= 6
                and row["avg_lift_pp"] >= 2
                and row["direction"] != "mixed"
            ):
                flag = " [*]"
            print(
                f"  {row['param']:<42} {row['direction']:<14} "
                f"{row['stability_score']:>2}/{row['n_years_tested']:<2}  "
                f"{row['avg_lift_pp']:>5.1f}pp{flag}"
            )


def main() -> None:
    df      = load_data()
    results = run_analysis(df)

    out_path = Path(__file__).parent / "correlation_stability.csv"
    results.to_csv(out_path, index=False)
    logger.info("Saved %d rows to %s", len(results), out_path)

    _print_results(results)


if __name__ == "__main__":
    main()

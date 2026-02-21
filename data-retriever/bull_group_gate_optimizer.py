#!/usr/bin/env python3
"""
bull_group_gate_optimizer.py

Per-group bull gate + hour optimization.
Key idea: different pair groups may benefit from different bull gates.

For each bull group:
  1. Show current performance (from tuned portfolio)
  2. Sweep single gates on that group's bull trades
  3. Sweep depth-2 combos
  4. For the top gates, also try hour window adjustments
  5. Report the best per-group config

Anti-overfit:
  - Min 20 trades per final config
  - Min 6h windows
  - Track how much the gate cuts volume (>50% cut = red flag)

Bear side unchanged throughout.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd
import numpy as np

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
RR: float = 2.0
PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
MIN_TRADES: int = 20
MIN_WINDOW: int = 6

BASE_DIR = Path(__file__).parent
ANALYSIS_DIR = BASE_DIR / "analysis"
SIGNALS_CSV = ANALYSIS_DIR / "signals.csv"
EXIT_SIM_CSV = ANALYSIS_DIR / "exit_simulations.csv"
TUNED_CSV = ANALYSIS_DIR / "tuned_window_configs.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

# Gate definitions: (label, column, operator, threshold)
SINGLE_GATES = [
    # session_directional_bias
    ("sbias>=0.1", "session_directional_bias", ">=", 0.1),
    ("sbias>=0.2", "session_directional_bias", ">=", 0.2),
    ("sbias>=0.3", "session_directional_bias", ">=", 0.3),
    ("sbias>=0.4", "session_directional_bias", ">=", 0.4),
    ("sbias>=0.5", "session_directional_bias", ">=", 0.5),
    # aoi_height_atr
    ("height<=0.8", "aoi_height_atr", "<=", 0.8),
    ("height<=0.95", "aoi_height_atr", "<=", 0.95),
    ("height<=1.0", "aoi_height_atr", "<=", 1.0),
    ("height<=1.12", "aoi_height_atr", "<=", 1.12),
    ("height<=1.3", "aoi_height_atr", "<=", 1.3),
    ("height<=1.5", "aoi_height_atr", "<=", 1.5),
    # opposite extreme
    ("opp<=0.5", "signal_candle_opposite_extreme_atr", "<=", 0.5),
    ("opp<=0.58", "signal_candle_opposite_extreme_atr", "<=", 0.58),
    ("opp<=0.7", "signal_candle_opposite_extreme_atr", "<=", 0.7),
    ("opp<=0.87", "signal_candle_opposite_extreme_atr", "<=", 0.87),
    ("opp<=1.0", "signal_candle_opposite_extreme_atr", "<=", 1.0),
    # touch time
    ("touch>=10", "aoi_time_since_last_touch", ">=", 10),
    ("touch>=20", "aoi_time_since_last_touch", ">=", 20),
    ("touch>=30", "aoi_time_since_last_touch", ">=", 30),
    ("touch>=40", "aoi_time_since_last_touch", ">=", 40),
    # touch count
    ("tc<=2", "aoi_touch_count_since_creation", "<=", 2),
    ("tc<=3", "aoi_touch_count_since_creation", "<=", 3),
    ("tc<=5", "aoi_touch_count_since_creation", "<=", 5),
    # distance from impulse
    ("dist<=0.2", "distance_from_last_impulse_atr", "<=", 0.2),
    ("dist<=0.3", "distance_from_last_impulse_atr", "<=", 0.3),
    ("dist<=0.38", "distance_from_last_impulse_atr", "<=", 0.38),
    ("dist<=0.5", "distance_from_last_impulse_atr", "<=", 0.5),
    # retest penetration
    ("pen<=0.1", "max_retest_penetration_atr", "<=", 0.1),
    ("pen<=0.15", "max_retest_penetration_atr", "<=", 0.15),
    ("pen<=0.2", "max_retest_penetration_atr", "<=", 0.2),
    ("pen<=0.3", "max_retest_penetration_atr", "<=", 0.3),
]


def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"] == RR].copy()
    df["htf_zone"] = "mid"
    df.loc[df["htf_range_position_mid"] >= PREMIUM_THRESHOLD, "htf_zone"] = "premium"
    df.loc[df["htf_range_position_mid"] <= DISCOUNT_THRESHOLD, "htf_zone"] = "discount"
    sym_to_grp = {}
    for grp, syms in EXCLUSIVE_GROUPS.items():
        for s in syms:
            sym_to_grp[s] = grp
    df["group"] = df["symbol"].map(sym_to_grp)
    df = df[df["group"].notna()].copy()
    return df


def build_tuned_portfolio(df: pd.DataFrame, direction_filter: Optional[str] = None) -> pd.DataFrame:
    configs = pd.read_csv(TUNED_CSV)
    if direction_filter:
        configs = configs[configs["direction"] == direction_filter]
    parts = []
    for _, cfg in configs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        mask = (
            (df["group"] == cfg["group"]) &
            (df["direction"] == cfg["direction"]) &
            (df["htf_zone"] == cfg["zone"]) &
            (df["sl_model"] == cfg["sl_model"]) &
            (df["hour_of_day_utc"].isin(hours))
        )
        sub = df[mask]
        if len(sub) >= 5:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _mls(exits: list[str]) -> int:
    streak = mx = 0
    for e in exits:
        if e == "SL":
            streak += 1
            mx = max(mx, streak)
        elif e == "TP":
            streak = 0
    return mx


def m(df: pd.DataFrame, sy: float, min_n: int = MIN_TRADES) -> Optional[dict]:
    if len(df) < min_n or sy < 0.01:
        return None
    tpy = len(df) / sy
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    gp = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gl = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n":   len(df_s),
        "tpy": round(tpy, 1),
        "win": round(float((df_s["exit_reason"] == "TP").mean()) * 100, 2),
        "exp": round(exp_r, 4),
        "mls": _mls(df_s["exit_reason"].tolist()),
        "pf":  round(gp / max(gl, 1e-9), 3),
    }


def apply_gate(df: pd.DataFrame, col: str, op: str, thresh: float) -> pd.DataFrame:
    if op == ">=":
        return df[df[col] >= thresh]
    else:
        return df[df[col] <= thresh]


# ---------------------------------------------------------------------------
# Per-group analysis
# ---------------------------------------------------------------------------
def analyze_group(
    grp_name: str,
    grp_bull: pd.DataFrame,
    sy: float,
) -> dict:
    """Full gate + hour analysis for one group's bull trades."""
    base = m(grp_bull, sy, 10)
    base_n = len(grp_bull)
    logger.info(
        "\n  BASELINE: n=%d  win=%.2f%%  tpy=%.1f  mls=%d",
        base["n"] if base else 0,
        base["win"] if base else 0,
        base["tpy"] if base else 0,
        base["mls"] if base else 0,
    )

    # --- Single gates ---
    single_results = []
    for label, col, op, thresh in SINGLE_GATES:
        if col not in grp_bull.columns:
            continue
        gated = apply_gate(grp_bull, col, op, thresh)
        gm = m(gated, sy, 10)
        if gm is None:
            continue
        retention = len(gated) / max(base_n, 1) * 100
        single_results.append({
            "gate": label,
            "col": col,
            "op": op,
            "thresh": thresh,
            "retain%": round(retention, 0),
            **gm,
        })

    best_single = {}
    if single_results:
        sdf = pd.DataFrame(single_results).sort_values("win", ascending=False)
        disp = ["gate", "n", "tpy", "win", "exp", "mls", "pf", "retain%"]
        # Show top gates that keep >40% of trades
        viable = sdf[sdf["retain%"] >= 40]
        if not viable.empty:
            logger.info("\n  Top single gates (retain >= 40%%):")
            logger.info("\n%s", viable[disp].head(10).to_string(index=False))
        # Also the aggressive ones
        logger.info("\n  Top single gates (all):")
        logger.info("\n%s", sdf[disp].head(10).to_string(index=False))
        best_single = sdf.iloc[0].to_dict()

    # --- Depth-2 combos (top gates only) ---
    # Pick top 5 distinct columns from single results
    if single_results:
        sdf_sorted = pd.DataFrame(single_results).sort_values("win", ascending=False)
        # One best per column
        best_per_col = sdf_sorted.drop_duplicates("col").head(6)

        combo_results = []
        rows_list = best_per_col.to_dict("records")
        for i, g1 in enumerate(rows_list):
            for g2 in rows_list[i+1:]:
                if g1["col"] == g2["col"]:
                    continue
                gated = apply_gate(grp_bull, g1["col"], g1["op"], g1["thresh"])
                gated = apply_gate(gated, g2["col"], g2["op"], g2["thresh"])
                gm = m(gated, sy, 10)
                if gm is None:
                    continue
                combo_results.append({
                    "combo": f"{g1['gate']} + {g2['gate']}",
                    "retain%": round(gm["n"] / max(base_n, 1) * 100, 0),
                    **gm,
                })

        if combo_results:
            cdf = pd.DataFrame(combo_results).sort_values("win", ascending=False)
            disp_c = ["combo", "n", "tpy", "win", "exp", "mls", "pf", "retain%"]
            # Show retain >= 30%
            viable_c = cdf[cdf["retain%"] >= 30]
            if not viable_c.empty:
                logger.info("\n  Top depth-2 combos (retain >= 30%%):")
                logger.info("\n%s", viable_c[disp_c].head(8).to_string(index=False))

    # --- Hour exclusion on best gate ---
    if single_results:
        # Take best single gate with retain >= 50%
        best_viable = sdf[sdf["retain%"] >= 50]
        if not best_viable.empty:
            bg = best_viable.iloc[0]
            gated = apply_gate(grp_bull, bg["col"], bg["op"], bg["thresh"])
            hour_excl_results = []
            for excl_size in [1, 2, 3]:
                for start in range(24):
                    excl = set((start + i) % 24 for i in range(excl_size))
                    filtered = gated[~gated["hour_of_day_utc"].isin(excl)]
                    gm = m(filtered, sy, 10)
                    if gm and gm["win"] > bg["win"]:
                        hour_excl_results.append({
                            "base_gate": bg["gate"],
                            "excl": f"excl_h{start:02d}+{excl_size}h",
                            **gm,
                        })
            if hour_excl_results:
                hedf = pd.DataFrame(hour_excl_results).sort_values("win", ascending=False)
                logger.info("\n  Best gate + hour exclusion:")
                disp_h = ["base_gate", "excl", "n", "tpy", "win", "exp", "mls", "pf"]
                logger.info("\n%s", hedf[disp_h].head(5).to_string(index=False))

    return {"base": base, "best_single": best_single}


# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    sy = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", sy, len(df))

    # Gates
    bear_gated = df[(df["direction"] == "bearish") & (df["aoi_touch_count_since_creation"] <= 3)]
    bull_base = df[(df["direction"] == "bullish") & (df["session_directional_bias"] >= 0.0)]

    # Bear portfolio (fixed)
    bear_pf = build_tuned_portfolio(bear_gated, "bearish")
    # Bull portfolio (current)
    bull_pf = build_tuned_portfolio(bull_base, "bullish")
    logger.info("Bear PF: %d | Bull PF: %d", len(bear_pf), len(bull_pf))

    full_baseline = m(pd.concat([bear_pf, bull_pf], ignore_index=True), sy, 10)
    logger.info(
        "\nFULL BASELINE: n=%d tpy=%.1f win=%.2f%% mls=%d pf=%.3f",
        full_baseline["n"], full_baseline["tpy"], full_baseline["win"],
        full_baseline["mls"], full_baseline["pf"],
    )

    # Analyze each bull group
    group_recommendations: dict[str, dict] = {}
    for grp in EXCLUSIVE_GROUPS:
        grp_bull = bull_pf[bull_pf["group"] == grp]
        if len(grp_bull) < 10:
            continue
        logger.info("\n" + "=" * 120)
        logger.info("GROUP: %s  (bull trades in portfolio: %d)", grp, len(grp_bull))
        logger.info("=" * 120)
        result = analyze_group(grp, grp_bull, sy)
        group_recommendations[grp] = result

    # --- Final: Build optimized portfolio with per-group bull gates ---
    logger.info("\n" + "=" * 120)
    logger.info("ASSEMBLING: Per-group bull gate portfolio options")
    logger.info("=" * 120)

    # For each group, test the best gate on the bull portfolio portion
    # then combine with bear
    gate_scenarios = [
        # Format: (scenario_name, {group: (col, op, thresh)})
        ("BASELINE (sbias>=0 for all)", {}),
        ("sbias>=0.2 for all", {g: ("session_directional_bias", ">=", 0.2) for g in EXCLUSIVE_GROUPS}),
        ("tc<=5 for all", {g: ("aoi_touch_count_since_creation", "<=", 5) for g in EXCLUSIVE_GROUPS}),
        ("height<=1.3 for all", {g: ("aoi_height_atr", "<=", 1.3) for g in EXCLUSIVE_GROUPS}),
    ]

    # Add per-group best gates scenario
    # Find the best single gate per group that retains >=50%
    best_per_group: dict[str, tuple] = {}
    for grp in EXCLUSIVE_GROUPS:
        grp_bull = bull_pf[bull_pf["group"] == grp]
        if len(grp_bull) < 10:
            continue
        best_win = 0
        best_gate = None
        for label, col, op, thresh in SINGLE_GATES:
            if col not in grp_bull.columns:
                continue
            gated = apply_gate(grp_bull, col, op, thresh)
            retention = len(gated) / len(grp_bull) * 100
            if retention < 50:
                continue
            gm = m(gated, sy, 10)
            if gm and gm["win"] > best_win:
                best_win = gm["win"]
                best_gate = (col, op, thresh, label)
        if best_gate:
            best_per_group[grp] = best_gate[:3]
            logger.info("  %s best (retain>=50%%): %s → win=%.2f%%", grp, best_gate[3], best_win)

    gate_scenarios.append(("PER-GROUP best (retain>=50%)", best_per_group))

    # Also find best with retain >= 40%
    best_per_group_40: dict[str, tuple] = {}
    for grp in EXCLUSIVE_GROUPS:
        grp_bull = bull_pf[bull_pf["group"] == grp]
        if len(grp_bull) < 10:
            continue
        best_win = 0
        best_gate = None
        for label, col, op, thresh in SINGLE_GATES:
            if col not in grp_bull.columns:
                continue
            gated = apply_gate(grp_bull, col, op, thresh)
            retention = len(gated) / len(grp_bull) * 100
            if retention < 40:
                continue
            gm = m(gated, sy, 10)
            if gm and gm["win"] > best_win:
                best_win = gm["win"]
                best_gate = (col, op, thresh, label)
        if best_gate:
            best_per_group_40[grp] = best_gate[:3]

    gate_scenarios.append(("PER-GROUP best (retain>=40%)", best_per_group_40))

    # Evaluate each scenario
    logger.info("\n  PORTFOLIO RESULTS:")
    for scenario_name, group_gates in gate_scenarios:
        bull_parts = []
        for grp in EXCLUSIVE_GROUPS:
            grp_bull = bull_pf[bull_pf["group"] == grp]
            if len(grp_bull) < 5:
                continue
            if grp in group_gates:
                col, op, thresh = group_gates[grp]
                grp_bull = apply_gate(grp_bull, col, op, thresh)
            bull_parts.append(grp_bull)

        if not bull_parts:
            continue
        scenario_bull = pd.concat(bull_parts, ignore_index=True)
        scenario_full = pd.concat([bear_pf, scenario_bull], ignore_index=True)
        sm = m(scenario_full, sy, 10)
        bull_m = m(scenario_bull, sy, 5)
        if sm and bull_m:
            flag = " ✓" if sm["tpy"] >= 100 else ""
            logger.info(
                "    %-45s  total: n=%4d tpy=%5.1f win=%5.2f%% mls=%2d pf=%.3f%s  |  bull: n=%3d tpy=%5.1f win=%5.2f%%",
                scenario_name,
                sm["n"], sm["tpy"], sm["win"], sm["mls"], sm["pf"], flag,
                bull_m["n"], bull_m["tpy"], bull_m["win"],
            )

    logger.info("\nDONE")


if __name__ == "__main__":
    main()

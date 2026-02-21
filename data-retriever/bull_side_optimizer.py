#!/usr/bin/env python3
"""
bull_side_optimizer.py

Focus: Improve bullish win% (currently 47.49%) closer to bearish (55.36%)
without shrinking bull TPY (currently ~57 tpy).

Approach:
1. Feature scan: sweep every available feature on bull trades, find what lifts win%
2. Depth-2 combos: try pairs of bull gates
3. Per-bucket bull analysis: which bull buckets are weak and can be improved?
4. Bull-specific hour tuning per bucket
5. Final recommendation: best bull gate that preserves volume

Uses tuned portfolio windows from tuned_window_configs.csv.
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

# All gatable features
FEATURES = [
    ("session_directional_bias", ">=", np.arange(-0.5, 1.01, 0.1)),
    ("aoi_height_atr", "<=", [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.12, 1.2, 1.3, 1.5, 1.8, 2.0]),
    ("signal_candle_opposite_extreme_atr", "<=", [0.3, 0.4, 0.5, 0.58, 0.65, 0.7, 0.8, 0.87, 1.0, 1.2, 1.5]),
    ("aoi_time_since_last_touch", ">=", [0, 5, 10, 15, 20, 25, 30, 40, 49, 60]),
    ("distance_from_last_impulse_atr", "<=", [0.1, 0.15, 0.2, 0.25, 0.3, 0.38, 0.5, 0.7, 1.0]),
    ("aoi_touch_count_since_creation", "<=", [1, 2, 3, 4, 5, 7, 10]),
    ("htf_range_position_mid", "<=", [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5]),
    ("htf_range_position_mid", ">=", [0.5, 0.6, 0.65, 0.7, 0.75, 0.8]),
    ("max_retest_penetration_atr", "<=", [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5]),
]


# ---------------------------------------------------------------------------
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


def build_tuned_portfolio(gated_df: pd.DataFrame) -> pd.DataFrame:
    """Build portfolio from tuned_window_configs.csv."""
    configs = pd.read_csv(TUNED_CSV)
    parts = []
    for _, cfg in configs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = gated_df[
            (gated_df["group"] == cfg["group"]) &
            (gated_df["direction"] == cfg["direction"]) &
            (gated_df["htf_zone"] == cfg["zone"]) &
            (gated_df["sl_model"] == cfg["sl_model"]) &
            (gated_df["hour_of_day_utc"].isin(hours))
        ]
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


def mets(df: pd.DataFrame, span_years: float, min_n: int = MIN_TRADES) -> Optional[dict]:
    if len(df) < min_n or span_years < 0.01:
        return None
    tpy = len(df) / span_years
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


# ---------------------------------------------------------------------------
# Phase 1: Single feature sweep on bull trades
# ---------------------------------------------------------------------------
def phase1_feature_sweep(bull_df: pd.DataFrame, sy: float) -> list[dict]:
    logger.info("\n" + "=" * 120)
    logger.info("PHASE 1: Single bull gate feature sweep")
    logger.info("=" * 120)

    base = mets(bull_df, sy, 10)
    if base:
        logger.info(
            "  BASELINE bull: n=%d  tpy=%.1f  win=%.2f%%  exp=%.4f  mls=%d  pf=%.3f",
            base["n"], base["tpy"], base["win"], base["exp"], base["mls"], base["pf"],
        )

    results = []
    for col, op, thresholds in FEATURES:
        if col not in bull_df.columns:
            continue
        for thresh in thresholds:
            thresh = round(float(thresh), 2)
            if op == ">=":
                mask = bull_df[col] >= thresh
                label = f"{col}>={thresh}"
            else:
                mask = bull_df[col] <= thresh
                label = f"{col}<={thresh}"
            filtered = bull_df[mask]
            m = mets(filtered, sy)
            if m is None:
                continue
            results.append({
                "gate": label,
                "col": col,
                "op": op,
                "thresh": thresh,
                **m,
            })

    if results:
        rdf = pd.DataFrame(results).sort_values("win", ascending=False)
        # Show top 25
        disp = ["gate", "n", "tpy", "win", "exp", "mls", "pf"]
        logger.info("\n  Top 25 single bull gates (by win%%):")
        logger.info("\n%s", rdf[disp].head(25).to_string(index=False))

        # Also show Pareto: tpy >= 40 (roughly half of baseline bull tpy)
        pareto = rdf[rdf["tpy"] >= 40].head(15)
        if not pareto.empty:
            logger.info("\n  Pareto: tpy >= 40:")
            logger.info("\n%s", pareto[disp].to_string(index=False))

    return results


# ---------------------------------------------------------------------------
# Phase 2: Depth-2 bull gate combos
# ---------------------------------------------------------------------------
def phase2_depth2_combos(bull_df: pd.DataFrame, sy: float, phase1: list[dict]) -> list[dict]:
    logger.info("\n" + "=" * 120)
    logger.info("PHASE 2: Depth-2 bull gate combinations (top features)")
    logger.info("=" * 120)

    # Pick top features from phase1 (best per column, tpy >= 30)
    p1_df = pd.DataFrame(phase1)
    p1_viable = p1_df[p1_df["tpy"] >= 30].copy()
    if p1_viable.empty:
        logger.info("  No viable single gates with tpy >= 30")
        return []

    # Best threshold per (col, op) with tpy >= 30
    best_per_feat = (
        p1_viable
        .sort_values("win", ascending=False)
        .drop_duplicates("col")
        .head(8)  # top 8 distinct features
    )
    logger.info("  Using features: %s", list(best_per_feat["gate"]))

    # Build candidate gate masks
    gate_defs: list[tuple[str, pd.Series]] = []
    for _, row in best_per_feat.iterrows():
        col = row["col"]
        thresh = row["thresh"]
        op = row["op"]
        if op == ">=":
            mask = bull_df[col] >= thresh
        else:
            mask = bull_df[col] <= thresh
        gate_defs.append((row["gate"], mask))

    # Also add a few extra thresholds for key features to get better combos
    extras = [
        ("sbias>=0.1", bull_df["session_directional_bias"] >= 0.1),
        ("sbias>=0.2", bull_df["session_directional_bias"] >= 0.2),
        ("sbias>=0.3", bull_df["session_directional_bias"] >= 0.3),
        ("height<=1.0", bull_df["aoi_height_atr"] <= 1.0),
        ("height<=1.12", bull_df["aoi_height_atr"] <= 1.12),
        ("height<=1.3", bull_df["aoi_height_atr"] <= 1.3),
        ("height<=1.5", bull_df["aoi_height_atr"] <= 1.5),
        ("opp<=0.58", bull_df["signal_candle_opposite_extreme_atr"] <= 0.58),
        ("opp<=0.87", bull_df["signal_candle_opposite_extreme_atr"] <= 0.87),
        ("touch>=10", bull_df["aoi_time_since_last_touch"] >= 10),
        ("touch>=25", bull_df["aoi_time_since_last_touch"] >= 25),
        ("touch>=40", bull_df["aoi_time_since_last_touch"] >= 40),
        ("tc<=3", bull_df["aoi_touch_count_since_creation"] <= 3),
        ("tc<=5", bull_df["aoi_touch_count_since_creation"] <= 5),
        ("dist<=0.2", bull_df["distance_from_last_impulse_atr"] <= 0.2),
        ("dist<=0.38", bull_df["distance_from_last_impulse_atr"] <= 0.38),
        ("pen<=0.1", bull_df["max_retest_penetration_atr"] <= 0.1),
        ("pen<=0.2", bull_df["max_retest_penetration_atr"] <= 0.2),
    ]
    gate_defs.extend(extras)

    # Deduplicate by name
    seen_names = set()
    unique_gates = []
    for name, mask in gate_defs:
        if name not in seen_names:
            seen_names.add(name)
            unique_gates.append((name, mask))

    results = []
    for i in range(len(unique_gates)):
        for j in range(i + 1, len(unique_gates)):
            name_a, mask_a = unique_gates[i]
            name_b, mask_b = unique_gates[j]
            # Skip combos of same feature
            col_a = name_a.split(">=")[0].split("<=")[0]
            col_b = name_b.split(">=")[0].split("<=")[0]
            if col_a == col_b:
                continue
            combined = bull_df[mask_a & mask_b]
            m = mets(combined, sy)
            if m is None:
                continue
            results.append({
                "gate1": name_a,
                "gate2": name_b,
                "combo": f"{name_a} + {name_b}",
                **m,
            })

    if results:
        rdf = pd.DataFrame(results).sort_values("win", ascending=False)
        disp = ["combo", "n", "tpy", "win", "exp", "mls", "pf"]

        logger.info("\n  Top 20 depth-2 combos (by win%%):")
        logger.info("\n%s", rdf[disp].head(20).to_string(index=False))

        # Pareto: tpy >= 40
        pareto = rdf[rdf["tpy"] >= 40].head(15)
        if not pareto.empty:
            logger.info("\n  Pareto (tpy >= 40):")
            logger.info("\n%s", pareto[disp].to_string(index=False))

        # Pareto: tpy >= 50 (close to current 56.9)
        pareto2 = rdf[rdf["tpy"] >= 50].head(15)
        if not pareto2.empty:
            logger.info("\n  Pareto (tpy >= 50, near-zero volume loss):")
            logger.info("\n%s", pareto2[disp].to_string(index=False))

    return results


# ---------------------------------------------------------------------------
# Phase 3: Per-bucket bull analysis
# ---------------------------------------------------------------------------
def phase3_per_bucket_bull(bull_df: pd.DataFrame, sy: float) -> None:
    logger.info("\n" + "=" * 120)
    logger.info("PHASE 3: Per-bucket bull breakdown (where are we losing?)")
    logger.info("=" * 120)

    configs = pd.read_csv(TUNED_CSV)
    bull_cfgs = configs[configs["direction"] == "bullish"]

    for _, cfg in bull_cfgs.iterrows():
        key = f"{cfg['group']}|{cfg['zone']}"
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = bull_df[
            (bull_df["group"] == cfg["group"]) &
            (bull_df["htf_zone"] == cfg["zone"]) &
            (bull_df["sl_model"] == cfg["sl_model"]) &
            (bull_df["hour_of_day_utc"].isin(hours))
        ]
        m = mets(sub, sy, 5)
        if m:
            flag = " ← WEAK" if m["win"] < 45 else ""
            logger.info(
                "  %-30s  SL=%-30s  n=%3d  tpy=%5.1f  win=%5.2f%%  mls=%d%s",
                key, cfg["sl_model"], m["n"], m["tpy"], m["win"], m["mls"], flag,
            )

            # If weak, show what gates help
            if m["win"] < 45 and len(sub) >= 20:
                logger.info("    → Testing gates on this weak bucket:")
                for col, op, _ in FEATURES[:5]:  # top 5 features
                    if col not in sub.columns:
                        continue
                    for thresh in [0.0, 0.1, 0.2, 0.3]:
                        if op == ">=":
                            gated = sub[sub[col] >= thresh]
                        else:
                            continue
                        gm = mets(gated, sy, 5)
                        if gm and gm["win"] > m["win"] + 3:
                            logger.info(
                                "      %s>=%s: n=%d win=%.2f%% (+%.2f%%)",
                                col, thresh, gm["n"], gm["win"], gm["win"] - m["win"],
                            )


# ---------------------------------------------------------------------------
# Phase 4: Full portfolio impact assessment
# ---------------------------------------------------------------------------
def phase4_portfolio_impact(
    bear_df: pd.DataFrame,
    bull_df: pd.DataFrame,
    sy: float,
    top_combos: list[dict],
) -> None:
    logger.info("\n" + "=" * 120)
    logger.info("PHASE 4: Full portfolio impact (bear unchanged + bull gated)")
    logger.info("=" * 120)

    base_full = pd.concat([bear_df, bull_df], ignore_index=True)
    base_m = mets(base_full, sy, 10)
    if base_m:
        logger.info(
            "  BASELINE: n=%d  tpy=%.1f  win=%.2f%%  exp=%.4f  mls=%d  pf=%.3f",
            base_m["n"], base_m["tpy"], base_m["win"], base_m["exp"], base_m["mls"], base_m["pf"],
        )

    # Test top bull gate combos on full portfolio
    gates_to_test = [
        ("sbias>=0.1", lambda df: df["session_directional_bias"] >= 0.1),
        ("sbias>=0.2", lambda df: df["session_directional_bias"] >= 0.2),
        ("sbias>=0.3", lambda df: df["session_directional_bias"] >= 0.3),
        ("height<=1.3", lambda df: df["aoi_height_atr"] <= 1.3),
        ("height<=1.5", lambda df: df["aoi_height_atr"] <= 1.5),
        ("opp<=0.87", lambda df: df["signal_candle_opposite_extreme_atr"] <= 0.87),
        ("touch>=10", lambda df: df["aoi_time_since_last_touch"] >= 10),
        ("tc<=3", lambda df: df["aoi_touch_count_since_creation"] <= 3),
        ("tc<=5", lambda df: df["aoi_touch_count_since_creation"] <= 5),
        ("pen<=0.2", lambda df: df["max_retest_penetration_atr"] <= 0.2),
        ("sbias>=0.1 + height<=1.5", lambda df: (df["session_directional_bias"] >= 0.1) & (df["aoi_height_atr"] <= 1.5)),
        ("sbias>=0.1 + opp<=0.87", lambda df: (df["session_directional_bias"] >= 0.1) & (df["signal_candle_opposite_extreme_atr"] <= 0.87)),
        ("sbias>=0.1 + touch>=10", lambda df: (df["session_directional_bias"] >= 0.1) & (df["aoi_time_since_last_touch"] >= 10)),
        ("sbias>=0.2 + height<=1.3", lambda df: (df["session_directional_bias"] >= 0.2) & (df["aoi_height_atr"] <= 1.3)),
        ("sbias>=0.2 + opp<=0.87", lambda df: (df["session_directional_bias"] >= 0.2) & (df["signal_candle_opposite_extreme_atr"] <= 0.87)),
        ("height<=1.3 + touch>=10", lambda df: (df["aoi_height_atr"] <= 1.3) & (df["aoi_time_since_last_touch"] >= 10)),
        ("height<=1.3 + opp<=0.87", lambda df: (df["aoi_height_atr"] <= 1.3) & (df["signal_candle_opposite_extreme_atr"] <= 0.87)),
        ("height<=1.5 + touch>=10", lambda df: (df["aoi_height_atr"] <= 1.5) & (df["aoi_time_since_last_touch"] >= 10)),
        ("tc<=5 + sbias>=0.1", lambda df: (df["aoi_touch_count_since_creation"] <= 5) & (df["session_directional_bias"] >= 0.1)),
        ("tc<=5 + height<=1.3", lambda df: (df["aoi_touch_count_since_creation"] <= 5) & (df["aoi_height_atr"] <= 1.3)),
        ("pen<=0.2 + sbias>=0.1", lambda df: (df["max_retest_penetration_atr"] <= 0.2) & (df["session_directional_bias"] >= 0.1)),
        ("pen<=0.2 + height<=1.5", lambda df: (df["max_retest_penetration_atr"] <= 0.2) & (df["aoi_height_atr"] <= 1.5)),
    ]

    rows = []
    for gate_name, gate_fn in gates_to_test:
        gated_bull = bull_df[gate_fn(bull_df)]
        full = pd.concat([bear_df, gated_bull], ignore_index=True)
        m = mets(full, sy, 10)
        bull_m = mets(gated_bull, sy, 10)
        if m and bull_m:
            rows.append({
                "bull_gate": gate_name,
                "total_n": m["n"],
                "total_tpy": m["tpy"],
                "total_win": m["win"],
                "total_mls": m["mls"],
                "total_pf": m["pf"],
                "bull_n": bull_m["n"],
                "bull_tpy": bull_m["tpy"],
                "bull_win": bull_m["win"],
                "bull_mls": bull_m["mls"],
            })

    if rows:
        rdf = pd.DataFrame(rows).sort_values("total_win", ascending=False)
        disp = ["bull_gate", "total_n", "total_tpy", "total_win", "total_mls", "total_pf",
                "bull_n", "bull_tpy", "bull_win", "bull_mls"]
        logger.info("\n  Full portfolio with various bull gates (bear side unchanged):")
        logger.info("\n%s", rdf[disp].to_string(index=False))

        # Highlight: tpy >= 100
        above100 = rdf[rdf["total_tpy"] >= 100]
        if not above100.empty:
            logger.info("\n  === tpy >= 100 only ===")
            logger.info("\n%s", above100[disp].to_string(index=False))


# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    sy = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", sy, len(df))

    # Apply bear gate
    bear = df["direction"] == "bearish"
    bull = df["direction"] == "bullish"
    bear_gated = df[bear & (df["aoi_touch_count_since_creation"] <= 3)]
    bull_base = df[bull & (df["session_directional_bias"] >= 0.0)]  # current permissive gate
    logger.info("Bear gated: %d | Bull base (sbias>=0): %d", len(bear_gated), len(bull_base))

    # Build tuned portfolio
    all_gated = pd.concat([bear_gated, bull_base], ignore_index=True)
    pf = build_tuned_portfolio(all_gated)
    bull_pf = pf[pf["direction"] == "bullish"]
    bear_pf = pf[pf["direction"] == "bearish"]
    logger.info("Tuned portfolio: %d total (%d bear, %d bull)", len(pf), len(bear_pf), len(bull_pf))

    p1 = phase1_feature_sweep(bull_pf, sy)
    p2 = phase2_depth2_combos(bull_pf, sy, p1)
    phase3_per_bucket_bull(bull_pf, sy)
    phase4_portfolio_impact(bear_pf, bull_pf, sy, p2)

    logger.info("\nDONE")


if __name__ == "__main__":
    main()

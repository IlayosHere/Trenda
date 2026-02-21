#!/usr/bin/env python3
"""
tpy100_optimizer.py

Goal: find the best gate configs that maintain >= 100 TPY.

Strategy 1: Config C (already 119 tpy) — apply hour exclusions to improve win%
Strategy 2: Relax bull gates in D/E/F configs to push volume from 80-90 → 100+ tpy
Strategy 3: Hybrid — try different bull gate threshold combos at the 100 tpy floor

Uses the same portfolio as bull_gate_explorer.py (CSV-based).

Usage:
    cd data-retriever
    python tpy100_optimizer.py
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RR: float = 2.0
PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
MIN_TRADES_ABS: int = 30
MIN_TPY: float = 100.0

BASE_DIR = Path(__file__).parent
ANALYSIS_DIR = BASE_DIR / "analysis"
SIGNALS_CSV = ANALYSIS_DIR / "signals.csv"
EXIT_SIM_CSV = ANALYSIS_DIR / "exit_simulations.csv"
BREAKDOWN_CSV = ANALYSIS_DIR / "htf_zone_breakdown.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}


# ---------------------------------------------------------------------------
# Data loading & portfolio (same as bull_gate_explorer)
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
    return df


def build_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    breakdown = pd.read_csv(BREAKDOWN_CSV)
    best = (
        breakdown
        .sort_values("win_pct", ascending=False)
        .drop_duplicates(subset=["group", "direction", "zone"])
    )
    parts: list[pd.DataFrame] = []
    for _, cfg in best.iterrows():
        grp: str = cfg["group"]
        hours: set[int] = set(ast.literal_eval(str(cfg["window_hours"])))
        sub = df[
            (df["symbol"].isin(EXCLUSIVE_GROUPS[grp])) &
            (df["direction"] == cfg["direction"]) &
            (df["htf_zone"] == cfg["zone"]) &
            (df["sl_model"] == cfg["sl_model"]) &
            (df["hour_of_day_utc"].isin(hours))
        ].copy()
        if len(sub) >= 10:
            sub["_bucket"] = f"{grp}|{cfg['direction']}|{cfg['zone']}"
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _mls(exits: list[str]) -> int:
    streak = mx = 0
    for e in exits:
        if e == "SL":
            streak += 1
            mx = max(mx, streak)
        elif e == "TP":
            streak = 0
    return mx


def compute_metrics(df: pd.DataFrame, span_years: float) -> Optional[dict]:
    if len(df) < MIN_TRADES_ABS or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
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


def fmt(label: str, m: Optional[dict]) -> str:
    if m is None:
        return f"  {label:65s}  ** insufficient **"
    flag = " ✓" if m["tpy"] >= MIN_TPY else ""
    return (
        f"  {label:65s}  n={m['n']:4d}  tpy={m['tpy']:6.1f}  "
        f"win={m['win']:5.2f}%  exp={m['exp']:.4f}  mls={m['mls']:2d}  pf={m['pf']:.3f}{flag}"
    )


# ---------------------------------------------------------------------------
# Strategy 1: Config C + hour exclusions
# ---------------------------------------------------------------------------
def strategy1_c_hour_exclusions(pf: pd.DataFrame, sy: float) -> None:
    logger.info("\n" + "=" * 110)
    logger.info("STRATEGY 1: Config C (tc<=3 bear + sbias>=0.2 bull) + hour exclusions")
    logger.info("=" * 110)

    bear = pf["direction"] == "bearish"
    bull = pf["direction"] == "bullish"
    mask_c = (bear & (pf["aoi_touch_count_since_creation"] <= 3)) | (bull & (pf["session_directional_bias"] >= 0.2))
    gated = pf[mask_c]

    base = compute_metrics(gated, sy)
    logger.info(fmt("Baseline C (no hour filter)", base))

    rows = []
    for excl_size in [2, 3, 4, 5, 6]:
        for start in range(24):
            excl = set((start + i) % 24 for i in range(excl_size))
            f = gated[~gated["hour_of_day_utc"].isin(excl)]
            m = compute_metrics(f, sy)
            if m and m["tpy"] >= MIN_TPY:
                rows.append({
                    "excl": f"excl_h{start:02d}+{excl_size}h",
                    **m,
                })
    if rows:
        rdf = pd.DataFrame(rows).sort_values("win", ascending=False)
        logger.info("\n  TOP configs with tpy >= %.0f:", MIN_TPY)
        disp = ["excl", "n", "tpy", "win", "exp", "mls", "pf"]
        logger.info("\n%s", rdf[disp].head(20).to_string(index=False))
    else:
        logger.info("  No hour exclusion keeps tpy >= %.0f", MIN_TPY)


# ---------------------------------------------------------------------------
# Strategy 2: Relax bull gates from D/E/F to push toward 100 tpy
# ---------------------------------------------------------------------------
def strategy2_relax_bull_gates(pf: pd.DataFrame, sy: float) -> None:
    logger.info("\n" + "=" * 110)
    logger.info("STRATEGY 2: Relax bull gate thresholds to push tpy toward 100+")
    logger.info("=" * 110)

    bear = pf["direction"] == "bearish"
    bull = pf["direction"] == "bullish"
    tc = pf["aoi_touch_count_since_creation"]

    # Bear hard gate is always tc<=3
    bear_mask = bear & (tc <= 3)

    # --- Config D variants: relax height and/or sbias ---
    logger.info("\n--- Config D variants: height <= X + sbias >= Y ---")
    rows_d = []
    for h_thresh in [0.95, 1.0, 1.05, 1.12, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0]:
        for s_thresh in [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4]:
            bull_mask = bull & (pf["aoi_height_atr"] <= h_thresh) & (pf["session_directional_bias"] >= s_thresh)
            combined = pf[bear_mask | bull_mask]
            m = compute_metrics(combined, sy)
            if m and m["tpy"] >= 80:  # show 80+ so user can see the frontier
                rows_d.append({
                    "height<=": h_thresh,
                    "sbias>=": s_thresh,
                    **m,
                })
    if rows_d:
        ddf = pd.DataFrame(rows_d).sort_values("win", ascending=False)
        # Mark ones at/above 100 tpy
        ddf["100+"] = ddf["tpy"].apply(lambda t: "✓" if t >= MIN_TPY else "")
        disp = ["height<=", "sbias>=", "n", "tpy", "win", "exp", "mls", "pf", "100+"]
        logger.info("\n  All combos (tpy >= 80), sorted by win%%:")
        logger.info("\n%s", ddf[disp].to_string(index=False))

        # Pareto frontier: tpy >= 100
        pareto = ddf[ddf["tpy"] >= MIN_TPY].head(15)
        if not pareto.empty:
            logger.info("\n  === PARETO: tpy >= 100, sorted by win%% ===")
            logger.info("\n%s", pareto[disp].to_string(index=False))

    # --- Config E variants: relax height and/or touch_time ---
    logger.info("\n--- Config E variants: height <= X + touch_time >= Y ---")
    rows_e = []
    for h_thresh in [0.95, 1.0, 1.12, 1.2, 1.3, 1.5, 1.8, 2.0]:
        for t_thresh in [0, 5, 10, 15, 20, 25, 30, 35, 40, 49]:
            bull_mask = bull & (pf["aoi_height_atr"] <= h_thresh) & (pf["aoi_time_since_last_touch"] >= t_thresh)
            combined = pf[bear_mask | bull_mask]
            m = compute_metrics(combined, sy)
            if m and m["tpy"] >= 80:
                rows_e.append({
                    "height<=": h_thresh,
                    "touch>=": t_thresh,
                    **m,
                })
    if rows_e:
        edf = pd.DataFrame(rows_e).sort_values("win", ascending=False)
        edf["100+"] = edf["tpy"].apply(lambda t: "✓" if t >= MIN_TPY else "")
        disp = ["height<=", "touch>=", "n", "tpy", "win", "exp", "mls", "pf", "100+"]
        pareto = edf[edf["tpy"] >= MIN_TPY].head(15)
        if not pareto.empty:
            logger.info("\n  === PARETO: tpy >= 100, sorted by win%% ===")
            logger.info("\n%s", pareto[disp].to_string(index=False))

    # --- Config F variants: relax height and/or opp_extreme ---
    logger.info("\n--- Config F variants: height <= X + opp_extreme <= Y ---")
    rows_f = []
    for h_thresh in [0.8, 0.9, 0.95, 1.0, 1.05, 1.12, 1.2, 1.3, 1.5, 1.8]:
        for o_thresh in [0.4, 0.5, 0.58, 0.65, 0.7, 0.8, 0.87, 1.0, 1.2, 1.5]:
            bull_mask = bull & (pf["aoi_height_atr"] <= h_thresh) & (pf["signal_candle_opposite_extreme_atr"] <= o_thresh)
            combined = pf[bear_mask | bull_mask]
            m = compute_metrics(combined, sy)
            if m and m["tpy"] >= 80:
                rows_f.append({
                    "height<=": h_thresh,
                    "opp<=": o_thresh,
                    **m,
                })
    if rows_f:
        fdf = pd.DataFrame(rows_f).sort_values("win", ascending=False)
        fdf["100+"] = fdf["tpy"].apply(lambda t: "✓" if t >= MIN_TPY else "")
        disp = ["height<=", "opp<=", "n", "tpy", "win", "exp", "mls", "pf", "100+"]
        pareto = fdf[fdf["tpy"] >= MIN_TPY].head(15)
        if not pareto.empty:
            logger.info("\n  === PARETO: tpy >= 100, sorted by win%% ===")
            logger.info("\n%s", pareto[disp].to_string(index=False))


# ---------------------------------------------------------------------------
# Strategy 3: Single bull gates at 100+ tpy
# ---------------------------------------------------------------------------
def strategy3_single_bull_gates(pf: pd.DataFrame, sy: float) -> None:
    logger.info("\n" + "=" * 110)
    logger.info("STRATEGY 3: tc<=3 bear + single bull gate sweeps at 100+ tpy")
    logger.info("=" * 110)

    bear = pf["direction"] == "bearish"
    bull = pf["direction"] == "bullish"
    bear_mask = bear & (pf["aoi_touch_count_since_creation"] <= 3)

    # Test single bull gates across key features
    gates = []
    for col, thresholds, op in [
        ("session_directional_bias", [-1.0, -0.5, 0.0, 0.1, 0.2, 0.3, 0.5], ">="),
        ("aoi_height_atr", [0.8, 0.9, 1.0, 1.12, 1.2, 1.3, 1.5, 1.8, 2.0], "<="),
        ("signal_candle_opposite_extreme_atr", [0.4, 0.5, 0.58, 0.7, 0.87, 1.0, 1.25], "<="),
        ("aoi_time_since_last_touch", [0, 5, 10, 20, 30, 40, 49], ">="),
        ("aoi_far_edge_atr", [1.0, 1.1, 1.2, 1.3, 1.43, 1.5, 1.7, 2.0], "<="),
        ("break_impulse_body_atr", [0.3, 0.37, 0.5, 0.64, 0.8, 1.0], "<="),
        ("aoi_near_edge_atr", [0.06, 0.1, 0.14, 0.2, 0.3, 0.5], "<="),
        ("distance_from_last_impulse_atr", [0.2, 0.3, 0.38, 0.5, 0.7, 1.0], "<="),
    ]:
        for thresh in thresholds:
            if op == ">=":
                bull_mask = bull & (pf[col] >= thresh)
                label = f"{col}>={thresh}"
            else:
                bull_mask = bull & (pf[col] <= thresh)
                label = f"{col}<={thresh}"
            combined = pf[bear_mask | bull_mask]
            m = compute_metrics(combined, sy)
            if m and m["tpy"] >= MIN_TPY:
                gates.append({"bull_gate": label, **m})

    if gates:
        gdf = pd.DataFrame(gates).sort_values("win", ascending=False)
        disp = ["bull_gate", "n", "tpy", "win", "exp", "mls", "pf"]
        logger.info("\n  Single bull gates with tpy >= 100:")
        logger.info("\n%s", gdf[disp].head(25).to_string(index=False))


# ---------------------------------------------------------------------------
# Strategy 4: Best single bull gate + hour exclusion
# ---------------------------------------------------------------------------
def strategy4_best_single_gate_plus_hours(pf: pd.DataFrame, sy: float) -> None:
    logger.info("\n" + "=" * 110)
    logger.info("STRATEGY 4: Best single bull gates + hour exclusion (tpy >= 100)")
    logger.info("=" * 110)

    bear = pf["direction"] == "bearish"
    bull = pf["direction"] == "bullish"
    bear_mask = bear & (pf["aoi_touch_count_since_creation"] <= 3)

    # Top single gates that have volume headroom for hour trimming
    top_gates = [
        ("sbias>=0.2", bull & (pf["session_directional_bias"] >= 0.2)),
        ("sbias>=0.1", bull & (pf["session_directional_bias"] >= 0.1)),
        ("sbias>=0.0", bull & (pf["session_directional_bias"] >= 0.0)),
        ("height<=1.5", bull & (pf["aoi_height_atr"] <= 1.5)),
        ("height<=1.3", bull & (pf["aoi_height_atr"] <= 1.3)),
        ("height<=1.12", bull & (pf["aoi_height_atr"] <= 1.12)),
        ("opp<=0.87", bull & (pf["signal_candle_opposite_extreme_atr"] <= 0.87)),
        ("opp<=0.58", bull & (pf["signal_candle_opposite_extreme_atr"] <= 0.58)),
        ("far_edge<=1.43", bull & (pf["aoi_far_edge_atr"] <= 1.43)),
    ]

    rows = []
    for gate_name, bull_mask in top_gates:
        gated = pf[bear_mask | bull_mask]
        # No hour exclusion
        m_base = compute_metrics(gated, sy)
        if m_base:
            rows.append({"gate": gate_name, "excl": "none", **m_base})

        # Hour exclusions
        for excl_size in [2, 3, 4, 5, 6]:
            for start in range(24):
                excl = set((start + i) % 24 for i in range(excl_size))
                f = gated[~gated["hour_of_day_utc"].isin(excl)]
                m = compute_metrics(f, sy)
                if m and m["tpy"] >= MIN_TPY:
                    rows.append({
                        "gate": gate_name,
                        "excl": f"excl_h{start:02d}+{excl_size}h",
                        **m,
                    })

    if rows:
        rdf = pd.DataFrame(rows).sort_values("win", ascending=False)
        disp = ["gate", "excl", "n", "tpy", "win", "exp", "mls", "pf"]
        logger.info("\n  Best combos (tpy >= 100):")
        logger.info("\n%s", rdf[disp].head(30).to_string(index=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", span_years, len(df))

    pf = build_portfolio(df)
    if pf.empty:
        logger.error("Portfolio empty")
        return
    logger.info("Portfolio: %d trades (%.1f tpy)", len(pf), len(pf) / span_years)

    strategy1_c_hour_exclusions(pf, span_years)
    strategy2_relax_bull_gates(pf, span_years)
    strategy3_single_bull_gates(pf, span_years)
    strategy4_best_single_gate_plus_hours(pf, span_years)

    logger.info("\n" + "=" * 110)
    logger.info("DONE")
    logger.info("=" * 110)


if __name__ == "__main__":
    main()

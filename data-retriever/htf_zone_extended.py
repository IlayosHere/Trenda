#!/usr/bin/env python3
"""
HTF zone extended optimizer.

Two targets, two routes — all gates from the existing analyzed library,
no new gate design, no cherry-picked thresholds.

QUALITY route:
  Base = bear[touch_count<=3] + bull[session_bias>=0.2] + universal[touch_count<=6]
         → 49.34% / 108.6 tpy (Phase B result)
  Sweep: 4th gate across all universal candidates
  Target: >= 50% win AND >= 100 tpy

VOLUME route:
  Bases = top high-volume Phase A combos (130–192 tpy at 45–47%)
  Sweep: depth-3 universal gate for each base
  Target: >= 46% win AND >= 150 tpy

Anti-overfitting:
  - No new gate columns introduced
  - Starting configs taken directly from Phase A/B analysis
  - Max depth: 4 total gates (2 dir-split + 2 universal)
  - Thresholds are quantile-derived or round values already validated

Output: analysis/htf_zone_extended.csv

Usage:
    cd data-retriever
    python htf_zone_extended.py
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

PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25
RR: float = 2.0
MIN_TRADES_ABS: int = 15

# Quality target
QUALITY_WIN_TARGET: float = 0.500
QUALITY_TPY_TARGET: float = 100.0

# Volume target
VOLUME_WIN_TARGET: float = 0.460
VOLUME_TPY_TARGET: float = 150.0

# Near-miss tolerance for reporting
WIN_NEAR_MISS: float = 0.005   # within 0.5pp of target
TPY_NEAR_MISS: float = 10.0   # within 10 tpy of target

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
BREAKDOWN_CSV = BASE_DIR / "htf_zone_breakdown.csv"
OUT_PATH = BASE_DIR / "htf_zone_extended.csv"

EXCLUSIVE_GROUPS: dict[str, list[str]] = {
    "jpy_pairs":   ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur_crosses": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp_crosses": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "commodity":   ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}

_EXCLUDE_GATE: set[str] = {
    "id", "entry_signal_id", "signal_time", "symbol", "direction",
    "sl_model", "rr_multiple", "sl_atr", "exit_reason", "return_r",
    "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "hour_of_day_utc", "htf_zone", "_bucket",
    "htf_range_position_mid", "htf_range_position_high",
    "trend_alignment_strength", "trend_age_bars_1h",
}

_DROP_DUPLICATE_COLS: set[str] = {
    "signal_candle_range_atr",
    "signal_candle_body_atr",
    "geo_aoi_height_atr",
}

# ---------------------------------------------------------------------------
# Starting configs (validated from Phase A / Phase B analysis)
# ---------------------------------------------------------------------------

# Quality route: already has 3 gates, sweep 4th
# Source: Phase B → bear[tc<=3] + bull[sb>=0.2] gives 48.56%/119tpy,
#         + universal[tc<=6] pushes to 49.34%/108.6 tpy
QUALITY_BASE = (
    "aoi_touch_count_since_creation<=3.0",   # bear gate
    "session_directional_bias>=0.2",          # bull gate
    "aoi_touch_count_since_creation<=6.0",    # universal gate 1
)

# Volume route: sweep 3rd gate (dir-split already applied)
# Source: Phase A high-tpy configs
VOLUME_BASES: list[tuple[str, str, str]] = [
    # (bear_gate, bull_gate, label)
    ("aoi_touch_count_since_creation<=3.0", "break_impulse_range_atr<=1.14",              "A_tc3_range1.14"),   # 191 tpy / 46.3%
    ("aoi_touch_count_since_creation<=3.0", "signal_candle_opposite_extreme_atr<=0.87",   "A_tc3_opp0.87"),     # 192 tpy / 46.0%
    ("aoi_touch_count_since_creation<=3.0", "break_impulse_body_atr<=0.64",               "A_tc3_body0.64"),    # 191 tpy / 46.0%
    ("aoi_touch_count_since_creation<=3.0", "aoi_near_edge_atr<=0.32",                    "A_tc3_near0.32"),    # 190 tpy / 45.6%
    ("aoi_touch_count_since_creation<=4.0", "session_directional_bias>=0.2",              "A_tc4_sb0.2"),       # 156 tpy / 45.7%
    ("aoi_touch_count_since_creation<=3.0", "aoi_height_atr<=1.12",                       "A_tc3_h1.12"),       # 134 tpy / 47.8%
    ("aoi_touch_count_since_creation<=3.0", "aoi_last_reaction_strength>=0.84",           "A_tc3_react0.84"),   # 122 tpy / 47.8%
]


# ---------------------------------------------------------------------------
# Data loading
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


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _max_losing_streak(exits: list[str]) -> int:
    streak = max_streak = 0
    for e in exits:
        if e == "SL":
            streak += 1
            max_streak = max(max_streak, streak)
        elif e == "TP":
            streak = 0
    return max_streak


def compute_metrics(
    df: pd.DataFrame,
    span_years: float,
    min_tpy: float = 0.0,
) -> Optional[dict]:
    if len(df) < MIN_TRADES_ABS or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    if tpy < min_tpy:
        return None
    df_s = df.sort_values("signal_time")
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
    gross_profit = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gross_loss = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades": len(df_s),
        "tpy": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(gross_profit / max(gross_loss, 1e-9), 3),
    }


# ---------------------------------------------------------------------------
# Portfolio reconstruction
# ---------------------------------------------------------------------------

def build_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    breakdown = pd.read_csv(BREAKDOWN_CSV)
    best = (
        breakdown
        .sort_values("win_pct", ascending=False)
        .drop_duplicates(subset=["group", "direction", "zone"])
    )
    parts: list[pd.DataFrame] = []
    for _, cfg in best.iterrows():
        hours = set(ast.literal_eval(str(cfg["window_hours"])))
        bucket_df = df[
            (df["symbol"].isin(EXCLUSIVE_GROUPS[cfg["group"]])) &
            (df["direction"] == cfg["direction"]) &
            (df["htf_zone"] == cfg["zone"]) &
            (df["sl_model"] == cfg["sl_model"]) &
            (df["hour_of_day_utc"].isin(hours))
        ].copy()
        if len(bucket_df) >= MIN_TRADES_ABS:
            bucket_df["_bucket"] = f"{cfg['group']}|{cfg['direction']}|{cfg['zone']}"
            parts.append(bucket_df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Gate utilities
# ---------------------------------------------------------------------------

def gate_mask(df: pd.DataFrame, name: str) -> pd.Series:
    """Parse gate name → boolean Series on df's index."""
    true_mask = pd.Series(True, index=df.index)
    if not name or name == "no_gate":
        return true_mask
    if ">=" in name:
        col, val = name.split(">=", 1)
        col = col.strip()
        if col in df.columns:
            return (df[col] >= float(val.strip())).fillna(False)
    if "<=" in name:
        col, val = name.split("<=", 1)
        col = col.strip()
        if col in df.columns:
            return (df[col] <= float(val.strip())).fillna(False)
    if name.endswith("_not_null"):
        col = name[:-9]
        if col in df.columns:
            return df[col].notna()
    if name.endswith("_null"):
        col = name[:-5]
        if col in df.columns:
            return df[col].isna()
    return true_mask


def apply_dir_gates(
    portfolio_df: pd.DataFrame,
    bear_gate_name: str,
    bull_gate_name: str,
) -> pd.DataFrame:
    bear_dir = portfolio_df["direction"] == "bearish"
    bull_dir = portfolio_df["direction"] == "bullish"
    bm = gate_mask(portfolio_df, bear_gate_name)
    um = gate_mask(portfolio_df, bull_gate_name)
    return portfolio_df[(bear_dir & bm) | (bull_dir & um)]


def build_universal_candidates(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    skip = _EXCLUDE_GATE | _DROP_DUPLICATE_COLS
    candidates: list[tuple[str, pd.Series]] = []
    for col in df.select_dtypes(include="number").columns:
        if col in skip:
            continue
        series = df[col].dropna()
        if len(series) < 100:
            continue
        for q in (0.25, 0.50, 0.75):
            thresh = round(float(series.quantile(q)), 2)
            candidates.append((f"{col}>={thresh}", (df[col] >= thresh).fillna(False)))
            candidates.append((f"{col}<={thresh}", (df[col] <= thresh).fillna(False)))
    for col in ["conflicted_tf", "session_directional_bias", "aoi_classification"]:
        if col in df.columns:
            candidates.append((f"{col}_null", df[col].isna()))
            candidates.append((f"{col}_not_null", df[col].notna()))
    return candidates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", span_years, len(df))

    portfolio_df = build_portfolio(df)
    if portfolio_df.empty:
        logger.error("Portfolio empty — run htf_zone_optimizer.py first")
        return

    logger.info("Portfolio (all buckets): %d trades | %.1f tpy", len(portfolio_df), len(portfolio_df) / span_years)

    all_results: list[dict] = []
    display_cols = ["route", "base", "gate3", "gate4", "n_trades", "tpy",
                    "win_pct", "expectancy_r", "max_losing_streak", "profit_factor"]

    # -----------------------------------------------------------------------
    # QUALITY route: bear[tc<=3] + bull[sb>=0.2] + univ[tc<=6] → sweep 4th gate
    # -----------------------------------------------------------------------
    logger.info("=== QUALITY ROUTE (target: win>=%.2f & tpy>=%.0f) ===",
                QUALITY_WIN_TARGET, QUALITY_TPY_TARGET)

    bear_g, bull_g, univ1_g = QUALITY_BASE
    q_phase_a = apply_dir_gates(portfolio_df, bear_g, bull_g)
    q_base = q_phase_a[gate_mask(q_phase_a, univ1_g)]
    q_base_m = compute_metrics(q_base, span_years)
    logger.info("Quality base (3 gates): %d trades | %.1f tpy | win=%.4f",
                len(q_base), len(q_base) / span_years, q_base_m["win_pct"] if q_base_m else 0)

    q_candidates = build_universal_candidates(q_base)
    logger.info("Sweeping %d candidates as 4th gate...", len(q_candidates))

    q_hits: list[dict] = []
    for name, mask in q_candidates:
        # Skip re-applying gates already in the chain
        if any(g in name for g in ["aoi_touch_count_since_creation", "session_directional_bias"]):
            continue
        filtered = q_base[mask.reindex(q_base.index, fill_value=False)]
        m = compute_metrics(filtered, span_years)
        if not m:
            continue
        is_target = m["win_pct"] >= QUALITY_WIN_TARGET and m["tpy"] >= QUALITY_TPY_TARGET
        is_near = (
            m["win_pct"] >= QUALITY_WIN_TARGET - WIN_NEAR_MISS and
            m["tpy"] >= QUALITY_TPY_TARGET - TPY_NEAR_MISS
        )
        if is_target or is_near:
            row = {
                "route": "quality",
                "base": f"bear[{bear_g}] + bull[{bull_g}] + {univ1_g}",
                "gate3": univ1_g,
                "gate4": name,
                "hits_target": is_target,
                **m,
            }
            q_hits.append(row)
            all_results.append(row)

    q_hits_sorted = sorted(q_hits, key=lambda r: r["win_pct"], reverse=True)
    if q_hits_sorted:
        logger.info("Quality route — configs meeting or near target (%d):", len(q_hits_sorted))
        for r in q_hits_sorted[:15]:
            logger.info(
                "  gate4=%-45s  win=%.4f  tpy=%.1f  mls=%d  exp=%.4f  %s",
                r["gate4"], r["win_pct"], r["tpy"], r["max_losing_streak"],
                r["expectancy_r"], "✓ TARGET" if r["hits_target"] else "near-miss",
            )
    else:
        logger.info("Quality route: no configs found near target. Best without gate filter:")
        if q_base_m:
            logger.info("  3-gate base: win=%.4f tpy=%.1f", q_base_m["win_pct"], q_base_m["tpy"])

    # -----------------------------------------------------------------------
    # VOLUME route: top-tpy Phase A bases → sweep 3rd universal gate
    # -----------------------------------------------------------------------
    logger.info("=== VOLUME ROUTE (target: win>=%.2f & tpy>=%.0f) ===",
                VOLUME_WIN_TARGET, VOLUME_TPY_TARGET)

    v_hits: list[dict] = []

    for bear_g, bull_g, label in VOLUME_BASES:
        v_base = apply_dir_gates(portfolio_df, bear_g, bull_g)
        v_base_m = compute_metrics(v_base, span_years)
        if not v_base_m:
            logger.info("  [%s] base failed metrics", label)
            continue
        logger.info(
            "  [%s] base (2 gates): %.1f tpy | win=%.4f | mls=%d",
            label, v_base_m["tpy"], v_base_m["win_pct"], v_base_m["max_losing_streak"],
        )

        v_candidates = build_universal_candidates(v_base)
        for name, mask in v_candidates:
            filtered = v_base[mask.reindex(v_base.index, fill_value=False)]
            m = compute_metrics(filtered, span_years)
            if not m:
                continue
            is_target = m["win_pct"] >= VOLUME_WIN_TARGET and m["tpy"] >= VOLUME_TPY_TARGET
            is_near = (
                m["win_pct"] >= VOLUME_WIN_TARGET - WIN_NEAR_MISS and
                m["tpy"] >= VOLUME_TPY_TARGET - TPY_NEAR_MISS
            )
            if is_target or is_near:
                row = {
                    "route": "volume",
                    "base": label,
                    "gate3": name,
                    "gate4": "",
                    "bear_gate": bear_g,
                    "bull_gate": bull_g,
                    "hits_target": is_target,
                    **m,
                }
                v_hits.append(row)
                all_results.append(row)

    v_hits_sorted = sorted(v_hits, key=lambda r: (r["hits_target"], r["win_pct"]), reverse=True)
    if v_hits_sorted:
        logger.info("Volume route — configs meeting or near target (%d total):", len(v_hits_sorted))
        # Deduplicate: show best per (base, gate3) sorted by win_pct
        seen: set[str] = set()
        shown = 0
        for r in v_hits_sorted:
            key = f"{r['base']}|{r['gate3']}"
            if key in seen:
                continue
            seen.add(key)
            logger.info(
                "  [%s] gate3=%-40s  win=%.4f  tpy=%.1f  mls=%d  %s",
                r["base"], r["gate3"], r["win_pct"], r["tpy"], r["max_losing_streak"],
                "✓ TARGET" if r["hits_target"] else "near-miss",
            )
            shown += 1
            if shown >= 20:
                break
    else:
        logger.info("Volume route: no configs found near target")

    # -----------------------------------------------------------------------
    # Save and summarize
    # -----------------------------------------------------------------------
    if all_results:
        out_df = pd.DataFrame(all_results)
        out_df.to_csv(OUT_PATH, index=False)
        logger.info("Saved %d results → %s", len(out_df), OUT_PATH)

        targets_hit = out_df[out_df["hits_target"]]
        if not targets_hit.empty:
            avail = [c for c in display_cols if c in targets_hit.columns]
            logger.info("=== CONFIGS HITTING TARGET (%d) ===", len(targets_hit))
            logger.info("\n%s", targets_hit.sort_values("win_pct", ascending=False)[avail].to_string(index=False))
        else:
            logger.info("No config hit both win AND tpy targets. Near-miss summary:")
            avail = [c for c in display_cols if c in out_df.columns]
            logger.info(
                "\n%s",
                out_df.sort_values("win_pct", ascending=False)[avail].head(10).to_string(index=False),
            )
    else:
        logger.info("No results generated — targets may be too strict")


if __name__ == "__main__":
    main()

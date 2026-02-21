#!/usr/bin/env python3
"""
Hour-exclusion tuner.

Approach:
  1. For each seed × symbol-group, compute per-hour win_pct / expectancy_r.
  2. Sort hours from worst to best (by expectancy_r).
  3. Try excluding the worst 1, 2, ..., N hours progressively — keeping
     all remaining hours (more quantity than a narrow window).
  4. For each viable exclusion mask (≥100 trades/yr, positive expectancy),
     sweep fine feature gates on top to further improve quality.

This is the inverse of a positive window: gate OUT bad hours,
keep the solid majority.

Seeds: top configs from previous analysis.
Output: analysis/hour_exclusion_results.csv  (sorted by win_pct desc)

Usage:
    cd data-retriever
    python hour_exclusion_tune.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import numpy as np
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MIN_TRADES_PER_YEAR: int = 100
FINE_PERCENTILES: tuple[int, ...] = tuple(range(5, 96, 5))

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "hour_exclusion_results.csv"

SYMBOL_GROUPS: dict[str, list[str]] = {
    "ALL":      [],   # empty = no filter
    "jpy_pairs":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "high_vol":   ["GBPJPY", "EURJPY", "GBPAUD", "GBPNZD", "EURAUD", "EURNZD"],
    "nzd_bloc":   ["NZDCAD", "NZDCHF", "NZDJPY", "NZDSGD", "NZDUSD", "EURNZD", "GBPNZD"],
    "eur_pairs":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "gbp_pairs":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "EURGBP"],
    "usd_majors": ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
}

# Seeds: feature gates ordered by priority (drop from end under volume pressure).
# gate = (label, fn)  — highest priority first
SEEDS: list[dict] = [
    {
        "sl_model": "SL_ATR_1_0",
        "rr_multiple": 2.0,
        "label": "ATR1",
        "feature_gates": [
            ("break_close_location<=0.921",
             lambda d: d["break_close_location"] <= 0.921),
        ],
    },
    {
        "sl_model": "SL_SIGNAL_CANDLE",
        "rr_multiple": 2.0,
        "label": "SIG_CANDLE",
        "feature_gates": [
            ("bearish_htf_mid>=0.829",
             lambda d: (d["direction"] == "bearish") & (d["htf_range_position_mid"] >= 0.829)),
            ("distance_obstacle<=1.060",
             lambda d: d["distance_to_next_htf_obstacle_atr"] <= 1.060),
        ],
    },
    {
        "sl_model": "SL_AOI_FAR",
        "rr_multiple": 2.0,
        "label": "AOI_FAR",
        "feature_gates": [
            ("bearish_aoi_midpoint>=0.545",
             lambda d: (d["direction"] == "bearish") & (d["aoi_midpoint_range_position_high"] >= 0.545)),
            ("aoi_height>=1.512",
             lambda d: d["aoi_height_atr"] >= 1.512),
        ],
    },
]

_EXCLUDE_COLS: frozenset[str] = frozenset({
    "entry_signal_id", "id", "rr_multiple", "sl_atr",
    "exit_reason", "return_r", "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "signal_time",
})
_RANGE_POS_COLS: frozenset[str] = frozenset({
    "htf_range_position_mid", "htf_range_position_high",
    "aoi_midpoint_range_position_mid", "aoi_midpoint_range_position_high",
})
_ORDINAL: frozenset[str] = frozenset({
    "trend_alignment_strength", "aoi_touch_count_since_creation",
})

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"].isin({s["rr_multiple"] for s in SEEDS})].copy()
    logger.info("Loaded %d rows | %d unique signals", len(df), df["entry_signal_id"].nunique())
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


def compute_metrics(df: pd.DataFrame, span_years: float) -> Optional[dict]:
    if len(df) < 5 or span_years < 0.01:
        return None
    tpy = len(df) / span_years
    if tpy < MIN_TRADES_PER_YEAR:
        return None
    df_s = df.sort_values("signal_time")
    gross_profit = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gross_loss = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    exp_r = float(df_s["return_r"].mean())
    if exp_r <= 0:
        return None
    return {
        "n_trades": len(df_s),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "sl_pct": round(float((df_s["exit_reason"] == "SL").mean()), 4),
        "timeout_pct": round(float((df_s["exit_reason"] == "TIMEOUT").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gross_profit / max(gross_loss, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Per-hour ranking
# ---------------------------------------------------------------------------

def rank_hours_by_expectancy(subset: pd.DataFrame) -> list[int]:
    """Return list of hours sorted worst (lowest exp_r) to best."""
    per_hour = (
        subset.groupby("hour_of_day_utc")["return_r"]
        .mean()
        .sort_values()
    )
    return per_hour.index.tolist()


# ---------------------------------------------------------------------------
# Fine gate candidates (for quality-boost step)
# ---------------------------------------------------------------------------

def build_fine_gates(df: pd.DataFrame) -> list[dict]:
    gates: list[dict] = []

    # Ordinals
    for thresh in (2, 3):
        gates.append({
            "name": f"trend_alignment_strength>={thresh}",
            "fn": lambda d, t=thresh: d["trend_alignment_strength"] >= t,
        })
    for thresh in (1, 2, 3):
        gates.append({
            "name": f"aoi_touch_count<={thresh}",
            "fn": lambda d, t=thresh: d["aoi_touch_count_since_creation"] <= t,
        })

    # Numeric cols at fine percentiles
    numeric_cols = [
        c for c in df.select_dtypes(include="number").columns
        if c not in _EXCLUDE_COLS and c not in _RANGE_POS_COLS and c not in _ORDINAL
    ]
    for col in numeric_cols:
        seen: set[float] = set()
        for pct in FINE_PERCENTILES:
            thresh = float(df[col].quantile(pct / 100))
            if np.isnan(thresh) or thresh in seen:
                continue
            seen.add(thresh)
            gates.append({
                "name": f"{col}>={thresh:.4f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: d[c] >= t,
            })
            gates.append({
                "name": f"{col}<={thresh:.4f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: d[c] <= t,
            })

    # Direction-split range-position cols
    for col in _RANGE_POS_COLS:
        if col not in df.columns:
            continue
        seen = set()
        for pct in FINE_PERCENTILES:
            thresh = float(df[col].quantile(pct / 100))
            if np.isnan(thresh) or thresh in seen:
                continue
            seen.add(thresh)
            gates.append({
                "name": f"bearish__{col}>={thresh:.4f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: (d["direction"] == "bearish") & (d[c] >= t),
            })
            gates.append({
                "name": f"bullish__{col}<={thresh:.4f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: (d["direction"] == "bullish") & (d[c] <= t),
            })
            gates.append({
                "name": f"dir_aware__{col}_p{pct}",
                "fn": lambda d, c=col, t=thresh: (
                    ((d["direction"] == "bullish") & (d[c] <= t))
                    | ((d["direction"] == "bearish") & (d[c] >= t))
                ),
            })

    # Categorical
    for val in df["conflicted_tf"].dropna().unique() if "conflicted_tf" in df.columns else []:
        gates.append({
            "name": f"conflicted_tf=={val!r}",
            "fn": lambda d, v=val: d["conflicted_tf"] == v,
        })
    gates.append({"name": "conflicted_tf_is_null",
                  "fn": lambda d: d["conflicted_tf"].isnull()})

    return gates


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years", span_years)

    fine_gates = build_fine_gates(df)
    logger.info("Built %d fine gate candidates", len(fine_gates))

    all_rows: list[dict] = []

    for seed in SEEDS:
        sl_model = seed["sl_model"]
        rr = seed["rr_multiple"]
        seed_label = seed["label"]
        feat_fns = [fn for _, fn in seed["feature_gates"]]
        feat_labels = [lbl for lbl, _ in seed["feature_gates"]]

        base_subset = df[(df["sl_model"] == sl_model) & (df["rr_multiple"] == rr)].copy()
        if base_subset.empty:
            continue

        for grp_name, grp_syms in SYMBOL_GROUPS.items():
            sym_subset = (
                base_subset if not grp_syms
                else base_subset[base_subset["symbol"].isin(grp_syms)]
            )
            if sym_subset.empty:
                continue

            # Apply feature gates progressively (start with all, relax if needed)
            # Pick the tightest feature gate set that still has enough raw volume
            working_subset = sym_subset.copy()
            active_feat_labels: list[str] = []
            for lbl, fn in zip(feat_labels, feat_fns):
                candidate = working_subset[fn(working_subset)]
                if len(candidate) / span_years >= MIN_TRADES_PER_YEAR * 0.5:
                    working_subset = candidate
                    active_feat_labels.append(lbl)
                # else: drop this gate, keep working_subset as-is

            if len(working_subset) < 10:
                continue

            # Per-hour ranking on the (potentially feature-gated) subset
            hours_worst_to_best = rank_hours_by_expectancy(working_subset)
            all_hours = set(range(24))
            logger.info(
                "  [%s | %s | %s] hours worst→best: %s",
                seed_label, grp_name,
                "+".join(active_feat_labels) or "no-feat",
                hours_worst_to_best,
            )

            # Exclusion sweep: exclude worst 1, 2, 3, ... hours
            base_feat_str = " & ".join(active_feat_labels) if active_feat_labels else "no_feat"
            for n_exclude in range(1, 17):
                excluded = set(hours_worst_to_best[:n_exclude])
                kept = sorted(all_hours - excluded)
                mask = working_subset["hour_of_day_utc"].isin(kept)
                filtered = working_subset[mask]
                m = compute_metrics(filtered, span_years)
                if m is None:
                    continue

                excl_str = "excl_h" + "_".join(str(h) for h in sorted(excluded))
                gate_str = f"{base_feat_str} & {excl_str}" if base_feat_str != "no_feat" else excl_str
                row = {
                    "seed": seed_label,
                    "sl_model": sl_model,
                    "rr_multiple": rr,
                    "sym_filter": grp_name,
                    "n_feat_gates": len(active_feat_labels),
                    "n_excluded_hours": n_exclude,
                    "excluded_hours": str(sorted(excluded)),
                    "kept_hours": str(kept),
                    "gate_str": gate_str,
                    **m,
                }
                all_rows.append(row)

                # Quality-boost: add 1 fine gate on top of this exclusion mask
                for fg in fine_gates:
                    try:
                        boosted = filtered[fg["fn"](filtered)]
                        mb = compute_metrics(boosted, span_years)
                        if mb and mb["win_pct"] > m["win_pct"]:
                            boost_gate = f"{gate_str} & {fg['name']}"
                            all_rows.append({
                                "seed": seed_label,
                                "sl_model": sl_model,
                                "rr_multiple": rr,
                                "sym_filter": grp_name,
                                "n_feat_gates": len(active_feat_labels) + 1,
                                "n_excluded_hours": n_exclude,
                                "excluded_hours": str(sorted(excluded)),
                                "kept_hours": str(kept),
                                "gate_str": boost_gate,
                                **mb,
                            })
                    except Exception:  # noqa: BLE001
                        pass

            logger.info("  [%s | %s] done. Rows so far: %d", seed_label, grp_name, len(all_rows))

    if not all_rows:
        logger.error("No results produced.")
        return

    result = (
        pd.DataFrame(all_rows)
        .drop_duplicates(subset=["sl_model", "rr_multiple", "gate_str"])
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )

    result.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(result), OUT_PATH)

    cols = ["seed", "sl_model", "rr_multiple", "sym_filter",
            "n_feat_gates", "n_excluded_hours",
            "n_trades", "trades_per_year", "win_pct",
            "expectancy_r", "max_losing_streak", "profit_factor",
            "excluded_hours", "gate_str"]
    avail = [c for c in cols if c in result.columns]

    logger.info("=== TOP 30 BY WIN_PCT ===")
    logger.info("\n%s", result[avail].head(30).to_string(index=False))

    logger.info("=== TOP 20 BY EXPECTANCY_R ===")
    logger.info("\n%s",
                result[avail].sort_values("expectancy_r", ascending=False)
                .head(20).to_string(index=False))

    # Best exclusion-only (no quality boost gate) per seed
    excl_only = result[result["gate_str"].str.count(" & ") <= result["n_excluded_hours"].apply(lambda x: 0)]
    logger.info("=== EXCLUSION-ONLY BEST (no quality gate) ===")
    # just filter where gate_str doesn't contain a quality gate beyond exclusion
    base_only = result[~result["gate_str"].str.contains(r"\(p\d+\)", regex=True)
                       & ~result["gate_str"].str.contains("trend_alignment|aoi_touch|bearish__|bullish__|dir_aware|conflicted_tf")]
    logger.info("\n%s", base_only[avail].head(20).to_string(index=False))

    logger.info("=== STREAK <= 10 BEST ===")
    low_streak = result[result["max_losing_streak"] <= 10].sort_values("win_pct", ascending=False)
    logger.info("\n%s", low_streak[avail].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

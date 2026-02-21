#!/usr/bin/env python3
"""
Deep-tune the best identified seed configurations.

For each seed (sl_model × rr_multiple × base gate combo):
  1. Evaluate seed alone
  2. Fine single-gate sweep  — all numeric cols at p5..p95 step 5
  3. Seed extension          — seed_mask & each fine gate candidate → depth-3
  4. Greedy win_pct forward selection (win_pct-optimised, not expectancy)
  5. Bearish HTF × fine numeric cross-product (fresh, not seeded)

Constraint: ≥100 trades/year, positive expectancy.
Output: analysis/deep_tune_results.csv (sorted by win_pct desc)

Usage:
    cd data-retriever
    python deep_tune.py
"""
from __future__ import annotations

from itertools import combinations
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
FINE_PERCENTILES: tuple[int, ...] = tuple(range(5, 96, 5))   # p5, p10, …, p95
MAX_EXTENSION_GATES: int = 500   # cap for seed-extension loop

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "deep_tune_results.csv"

# ---------------------------------------------------------------------------
# Seed configurations (best from analyze_system_config results)
# ---------------------------------------------------------------------------
# Each seed defines sl_model, rr_multiple, a pre-built mask function and a
# human-readable label.  gate_fn receives the (sl_model, rr) subset DataFrame.
SEEDS: list[dict] = [
    {
        "sl_model": "SL_AOI_FAR",
        "rr_multiple": 2.0,
        "label": "AOI_FAR_RR2",
        "gate_name": "aoi_height_atr>=1.512 & bearish__aoi_midpoint_range_position_high>=0.545",
        "gate_fn": lambda d: (
            (d["aoi_height_atr"] >= 1.512)
            & (d["direction"] == "bearish")
            & (d["aoi_midpoint_range_position_high"] >= 0.545)
        ),
    },
    {
        "sl_model": "SL_SIGNAL_CANDLE",
        "rr_multiple": 2.0,
        "label": "SIG_CANDLE_RR2",
        "gate_name": "distance_to_next_htf_obstacle_atr<=1.060 & bearish__htf_range_position_mid>=0.829",
        "gate_fn": lambda d: (
            (d["distance_to_next_htf_obstacle_atr"] <= 1.060)
            & (d["direction"] == "bearish")
            & (d["htf_range_position_mid"] >= 0.829)
        ),
    },
    {
        "sl_model": "SL_ATR_1_0",
        "rr_multiple": 2.0,
        "label": "ATR1_RR2_H8",
        "gate_name": "break_close_location<=0.921 & hour==8",
        "gate_fn": lambda d: (
            (d["break_close_location"] <= 0.921)
            & (d["hour_of_day_utc"] == 8)
        ),
    },
]

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    df = df[df["rr_multiple"].isin({s["rr_multiple"] for s in SEEDS})].copy()
    logger.info(
        "Loaded %d rows | %d unique signals",
        len(df), df["entry_signal_id"].nunique(),
    )
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
        return None   # skip negative-expectancy configs entirely
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
# Gate candidate builder (fine-grained)
# ---------------------------------------------------------------------------

_EXCLUDE: frozenset[str] = frozenset({
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
_CATEGORICAL: frozenset[str] = frozenset({
    "conflicted_tf", "aoi_classification", "symbol", "direction",
})
_SESSIONS: tuple[tuple[str, int, int], ...] = (
    ("asia(0-5)",       0,  5),
    ("london(6-11)",    6, 11),
    ("ny(12-17)",      12, 17),
    ("london_ny(6-17)", 6, 17),
)


def build_fine_gates(df: pd.DataFrame) -> list[dict]:
    gates: list[dict] = []

    # --- Categoricals ---
    gates.append({"name": "conflicted_tf_is_null",
                  "fn": lambda d: d["conflicted_tf"].isnull()})
    gates.append({"name": "conflicted_tf_is_not_null",
                  "fn": lambda d: d["conflicted_tf"].notnull()})
    for val in df["conflicted_tf"].dropna().unique():
        gates.append({
            "name": f"conflicted_tf=={val!r}",
            "fn": lambda d, v=val: d["conflicted_tf"] == v,
        })
    for val in df["aoi_classification"].dropna().unique() if "aoi_classification" in df.columns else []:
        gates.append({
            "name": f"aoi_classification=={val!r}",
            "fn": lambda d, v=val: d["aoi_classification"] == v,
        })
    for val in sorted(df["symbol"].dropna().unique()):
        gates.append({"name": f"symbol=={val!r}", "fn": lambda d, v=val: d["symbol"] == v})

    # --- Ordinals ---
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

    # --- All numeric cols — fine percentiles p5..p95 step 5 ---
    numeric_cols = [
        c for c in df.select_dtypes(include="number").columns
        if c not in _EXCLUDE and c not in _RANGE_POS_COLS and c not in _ORDINAL
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

    # --- Direction-split range-position cols — fine percentiles ---
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
                "name": f"bullish__{col}<={thresh:.4f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: (d["direction"] == "bullish") & (d[c] <= t),
            })
            gates.append({
                "name": f"bearish__{col}>={thresh:.4f}(p{pct})",
                "fn": lambda d, c=col, t=thresh: (d["direction"] == "bearish") & (d[c] >= t),
            })
            gates.append({
                "name": f"dir_aware__{col}_p{pct}",
                "fn": lambda d, c=col, t=thresh: (
                    ((d["direction"] == "bullish") & (d[c] <= t))
                    | ((d["direction"] == "bearish") & (d[c] >= t))
                ),
            })

    # --- Session / hour ---
    for sess_name, hs, he in _SESSIONS:
        gates.append({
            "name": sess_name,
            "fn": lambda d, a=hs, b=he: d["hour_of_day_utc"].between(a, b),
        })
    for h in range(24):
        gates.append({"name": f"hour=={h}", "fn": lambda d, hh=h: d["hour_of_day_utc"] == hh})

    # --- Symbol × session / hour ---
    for sym in sorted(df["symbol"].dropna().unique()):
        for sess_name, hs, he in _SESSIONS:
            gates.append({
                "name": f"symbol=={sym!r} & {sess_name}",
                "fn": lambda d, s=sym, a=hs, b=he: (
                    (d["symbol"] == s) & d["hour_of_day_utc"].between(a, b)
                ),
            })
        for h in range(24):
            gates.append({
                "name": f"symbol=={sym!r} & hour=={h}",
                "fn": lambda d, s=sym, hh=h: (d["symbol"] == s) & (d["hour_of_day_utc"] == hh),
            })

    logger.info("Built %d fine gate candidates", len(gates))
    return gates


# ---------------------------------------------------------------------------
# Evaluators
# ---------------------------------------------------------------------------

def _eval(
    subset: pd.DataFrame,
    mask: pd.Series,
    span_years: float,
    gate_label: str,
    sl_model: str,
    rr_multiple: float,
    source: str,
) -> Optional[dict]:
    filtered = subset[mask]
    m = compute_metrics(filtered, span_years)
    if m is None:
        return None
    return {"source": source, "sl_model": sl_model, "rr_multiple": rr_multiple,
            "gates": gate_label, **m}


def fine_single_sweep(
    subset: pd.DataFrame,
    gates: list[dict],
    span_years: float,
    sl_model: str,
    rr_multiple: float,
) -> list[dict]:
    rows = []
    for g in gates:
        try:
            mask = g["fn"](subset)
            r = _eval(subset, mask, span_years, g["name"], sl_model, rr_multiple, "fine_single")
            if r:
                rows.append(r)
        except Exception:  # noqa: BLE001
            pass
    return rows


def seed_extension(
    seed: dict,
    seed_mask: pd.Series,
    subset: pd.DataFrame,
    gates: list[dict],
    span_years: float,
) -> list[dict]:
    """Append each gate candidate to seed mask → depth-3 combo."""
    rows = []
    sl_model = seed["sl_model"]
    rr_multiple = seed["rr_multiple"]
    for g in gates[:MAX_EXTENSION_GATES]:
        try:
            combined_mask = seed_mask & g["fn"](subset)
            label = f"{seed['gate_name']} & {g['name']}"
            r = _eval(subset, combined_mask, span_years, label, sl_model, rr_multiple, "seed_ext")
            if r:
                rows.append(r)
        except Exception:  # noqa: BLE001
            pass
    return rows


def greedy_win_pct(
    seed: dict,
    seed_mask: pd.Series,
    subset: pd.DataFrame,
    gates: list[dict],
    span_years: float,
    max_depth: int = 5,
) -> list[dict]:
    """Forward greedy selection optimizing win_pct from seed mask."""
    current_mask = seed_mask.copy()
    m0 = compute_metrics(subset[current_mask], span_years)
    current_win = m0["win_pct"] if m0 else 0.0
    gate_names = [seed["gate_name"]]
    remaining = list(gates)
    rows: list[dict] = []

    for step in range(max_depth):
        best_gate = best_mask = best_win = None
        best_m = None
        for g in remaining:
            try:
                candidate_mask = current_mask & g["fn"](subset)
                m = compute_metrics(subset[candidate_mask], span_years)
                if m and m["win_pct"] > (best_win or current_win):
                    best_win = m["win_pct"]
                    best_gate = g
                    best_mask = candidate_mask
                    best_m = m
            except Exception:  # noqa: BLE001
                pass
        if best_gate is None:
            break
        gate_names.append(best_gate["name"])
        current_mask = best_mask
        current_win = best_win
        remaining.remove(best_gate)
        label = " & ".join(gate_names)
        rows.append({
            "source": f"greedy_step{step + 1}",
            "sl_model": seed["sl_model"],
            "rr_multiple": seed["rr_multiple"],
            "gates": label,
            **best_m,
        })
        logger.info(
            "  Greedy [%s] step%d +%s → win=%.4f  exp=%.4f  trades/yr=%.1f  streak=%d",
            seed["label"], step + 1, best_gate["name"],
            best_m["win_pct"], best_m["expectancy_r"],
            best_m["trades_per_year"], best_m["max_losing_streak"],
        )
    return rows


def bearish_htf_cross(
    subset: pd.DataFrame,
    gates: list[dict],
    span_years: float,
    sl_model: str,
    rr_multiple: float,
) -> list[dict]:
    """Cross-product: every bearish HTF range gate × every other gate."""
    bearish_gates = [
        g for g in gates
        if g["name"].startswith("bearish__htf_range_position")
        or g["name"].startswith("bearish__aoi_midpoint")
    ]
    other_gates = [g for g in gates if g not in bearish_gates]
    rows = []
    for bg in bearish_gates:
        try:
            base_mask = bg["fn"](subset)
        except Exception:  # noqa: BLE001
            continue
        for og in other_gates:
            try:
                combined_mask = base_mask & og["fn"](subset)
                label = f"{bg['name']} & {og['name']}"
                r = _eval(subset, combined_mask, span_years, label, sl_model, rr_multiple,
                          "bearish_htf_cross")
                if r:
                    rows.append(r)
            except Exception:  # noqa: BLE001
                pass
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years", span_years)

    gates = build_fine_gates(df)

    all_rows: list[dict] = []

    for seed in SEEDS:
        sl_model = seed["sl_model"]
        rr = seed["rr_multiple"]
        label = seed["label"]
        logger.info("=== Tuning seed: %s ===", label)

        subset = df[(df["sl_model"] == sl_model) & (df["rr_multiple"] == rr)].copy()
        if subset.empty:
            logger.warning("No data for %s RR=%.1f", sl_model, rr)
            continue

        # Seed mask
        try:
            seed_mask = seed["gate_fn"](subset)
        except Exception as exc:
            logger.error("Seed gate_fn failed for %s: %s", label, exc)
            continue

        # 1. Seed alone
        r = _eval(subset, seed_mask, span_years, seed["gate_name"], sl_model, rr, "seed")
        if r:
            all_rows.append(r)
            logger.info("  Seed: win=%.4f  exp=%.4f  trades/yr=%.1f",
                        r["win_pct"], r["expectancy_r"], r["trades_per_year"])

        # 2. Fine single-gate sweep on this sl_model/rr subset
        logger.info("  [%s] Fine single sweep …", label)
        all_rows += fine_single_sweep(subset, gates, span_years, sl_model, rr)

        # 3. Seed extension (seed & each fine gate)
        logger.info("  [%s] Seed extension …", label)
        all_rows += seed_extension(seed, seed_mask, subset, gates, span_years)

        # 4. Greedy win_pct forward selection from seed
        logger.info("  [%s] Greedy win_pct selection …", label)
        all_rows += greedy_win_pct(seed, seed_mask, subset, gates, span_years)

    # 5. Bearish HTF cross-product (run on each seed's sl_model/rr, not seeded)
    for seed in SEEDS:
        sl_model = seed["sl_model"]
        rr = seed["rr_multiple"]
        logger.info("  [%s] Bearish HTF × fine cross …", seed["label"])
        subset = df[(df["sl_model"] == sl_model) & (df["rr_multiple"] == rr)].copy()
        all_rows += bearish_htf_cross(subset, gates, span_years, sl_model, rr)

    if not all_rows:
        logger.error("No results produced.")
        return

    result = (
        pd.DataFrame(all_rows)
        .drop_duplicates(subset=["sl_model", "rr_multiple", "gates"])
        .sort_values("win_pct", ascending=False)
        .reset_index(drop=True)
    )

    result.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d rows → %s", len(result), OUT_PATH)

    logger.info("=== TOP 30 BY WIN_PCT ===")
    cols = ["source", "sl_model", "rr_multiple", "gates",
            "n_trades", "trades_per_year", "win_pct",
            "expectancy_r", "max_losing_streak", "profit_factor"]
    avail = [c for c in cols if c in result.columns]
    logger.info("\n%s", result[avail].head(30).to_string(index=False))

    logger.info("=== TOP 30 BY EXPECTANCY_R ===")
    logger.info("\n%s",
                result[avail].sort_values("expectancy_r", ascending=False)
                .head(30).to_string(index=False))


if __name__ == "__main__":
    main()

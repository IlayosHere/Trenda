#!/usr/bin/env python3
"""
Trading configuration builder — exhaustive search.

Target: >= 100 trades/yr AND win_pct > 40%, not overfitted.

Approach:
  1. All seeds x pair groups x contiguous windows x single extra gates
  2. Depth-2 gate stacking on high-volume (>=200 tpy) base combos
  3. Per-symbol best-contiguous-window portfolios
  4. Per-group portfolios (each symbol uses its own best contiguous window)

Windows: named contiguous time blocks only.
Gates: all signal columns at p25/p50/p75 thresholds + categoricals + ordinals.

Output: analysis/trading_config_results.csv

Usage:
    cd data-retriever
    python trading_config_builder.py
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
MIN_TRADES_PER_YEAR: int = 100        # portfolio floor
MIN_TRADES_DISCOVERY: int = 15        # per-symbol discovery floor
MIN_TRADES_ABS: int = 10
TOXIC_WIN_PCT: float = 0.334          # RR=2 breakeven
TARGET_WIN_PCT: float = 0.400         # our goal

BASE_DIR = Path(__file__).parent / "analysis"
SIGNALS_CSV = BASE_DIR / "signals.csv"
EXIT_SIM_CSV = BASE_DIR / "exit_simulations.csv"
OUT_PATH = BASE_DIR / "trading_config_results.csv"

# ---------------------------------------------------------------------------
# Contiguous windows (UTC hours only — no scattered hours)
# ---------------------------------------------------------------------------
CONTIGUOUS_WINDOWS: dict[str, list[int]] = {
    "asia":          list(range(0, 6)),
    "pre_london":    list(range(4, 8)),
    "london_open":   list(range(6, 10)),
    "london":        list(range(6, 12)),
    "london_midday": list(range(8, 12)),
    "ld_ny_overlap": list(range(10, 15)),
    "ny_open":       list(range(12, 16)),
    "ny":            list(range(12, 18)),
    "london_ny":     list(range(6, 18)),
    "ny_afternoon":  list(range(14, 18)),
    "ny_close":      list(range(16, 20)),
    "late_session":  list(range(18, 22)),
    "off_hours":     list(range(20, 24)) + list(range(0, 4)),
}

# ---------------------------------------------------------------------------
# Pair groups
# ---------------------------------------------------------------------------
PAIR_GROUPS: dict[str, Optional[list[str]]] = {
    "all":        None,
    "jpy_pairs":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd_majors": ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
    "gbp_pairs":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "EURGBP"],
    "eur_pairs":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "aud_bloc":   ["AUDCAD", "AUDCHF", "AUDJPY", "AUDUSD", "EURAUD", "GBPAUD"],
    "nzd_bloc":   ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD", "EURNZD", "GBPNZD"],
    "high_vol":   ["GBPJPY", "EURJPY", "GBPAUD", "GBPNZD", "EURAUD", "EURNZD"],
}

# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------
SEEDS: list[dict] = [
    {
        "sl_model": "SL_ATR_1_0",
        "rr_multiple": 2.0,
        "label": "ATR1",
        "gate_fn": lambda d: d["break_close_location"] <= 0.921,
        "gate_name": "break_close_location<=0.921",
    },
    {
        "sl_model": "SL_SIGNAL_CANDLE",
        "rr_multiple": 2.0,
        "label": "SIG_CANDLE",
        "gate_fn": lambda d: (
            (d["direction"] == "bearish")
            & (d["htf_range_position_mid"] >= 0.829)
            & (d["distance_to_next_htf_obstacle_atr"] <= 1.060)
        ),
        "gate_name": "bearish & htf_mid>=0.829 & distance<=1.060",
    },
    {
        "sl_model": "SL_AOI_FAR",
        "rr_multiple": 2.0,
        "label": "AOI_FAR",
        "gate_fn": lambda d: (
            (d["direction"] == "bearish")
            & (d["aoi_midpoint_range_position_high"] >= 0.545)
            & (d["aoi_height_atr"] >= 1.512)
        ),
        "gate_name": "bearish & aoi_midpoint>=0.545 & aoi_height>=1.512",
    },
]

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    signals = pd.read_csv(SIGNALS_CSV)
    exits = pd.read_csv(EXIT_SIM_CSV)
    signals["signal_time"] = pd.to_datetime(signals["signal_time"], utc=True)
    df = exits.merge(signals, left_on="entry_signal_id", right_on="id", how="inner")
    rr_set = {s["rr_multiple"] for s in SEEDS}
    df = df[df["rr_multiple"].isin(rr_set)].copy()
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


def compute_metrics(
    df: pd.DataFrame,
    span_years: float,
    min_tpy: float = MIN_TRADES_PER_YEAR,
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
    gp = df_s.loc[df_s["return_r"] > 0, "return_r"].sum()
    gl = abs(df_s.loc[df_s["return_r"] < 0, "return_r"].sum())
    return {
        "n_trades": len(df_s),
        "trades_per_year": round(tpy, 1),
        "win_pct": round(float((df_s["exit_reason"] == "TP").mean()), 4),
        "sl_pct": round(float((df_s["exit_reason"] == "SL").mean()), 4),
        "timeout_pct": round(float((df_s["exit_reason"] == "TIMEOUT").mean()), 4),
        "expectancy_r": round(exp_r, 4),
        "max_losing_streak": _max_losing_streak(df_s["exit_reason"].tolist()),
        "profit_factor": round(float(gp / max(gl, 1e-9)), 3),
    }


# ---------------------------------------------------------------------------
# Gate builder — all signal columns
# ---------------------------------------------------------------------------

_POST_TRADE = frozenset({
    "entry_signal_id", "id", "rr_multiple", "sl_atr",
    "exit_reason", "return_r", "bars_to_tp_hit", "bars_to_sl_hit", "exit_bar",
    "signal_time",
})
_RANGE_POS_COLS = frozenset({
    "htf_range_position_mid", "htf_range_position_high",
    "aoi_midpoint_range_position_mid", "aoi_midpoint_range_position_high",
})


def build_gate_library(df: pd.DataFrame) -> list[dict]:
    """Build comprehensive gate candidates from all signal columns."""
    gates: list[dict] = []

    # Direction
    gates.append({"name": "bearish_only", "fn": lambda d: d["direction"] == "bearish"})
    gates.append({"name": "bullish_only", "fn": lambda d: d["direction"] == "bullish"})

    # No conflicted TF
    if "conflicted_tf" in df.columns:
        gates.append({"name": "no_conflict", "fn": lambda d: d["conflicted_tf"].isnull()})

    # AOI classification
    if "aoi_classification" in df.columns:
        for val in df["aoi_classification"].dropna().unique():
            gates.append({
                "name": f"aoi_class=={val}",
                "fn": (lambda d, v=val: d["aoi_classification"] == v),
            })

    # Ordinals
    if "trend_alignment_strength" in df.columns:
        for t in (2, 3):
            gates.append({
                "name": f"trend_alignment>={t}",
                "fn": (lambda d, tt=t: d["trend_alignment_strength"] >= tt),
            })
    if "aoi_touch_count_since_creation" in df.columns:
        for t in (1, 2, 3):
            gates.append({
                "name": f"aoi_touch<={t}",
                "fn": (lambda d, tt=t: d["aoi_touch_count_since_creation"] <= tt),
            })

    # All numeric signal columns — <= and >= at p25/p50/p75
    numeric_cols = [
        c for c in df.select_dtypes(include="number").columns
        if c not in _POST_TRADE
        and c not in _RANGE_POS_COLS
        and c not in {"trend_alignment_strength", "aoi_touch_count_since_creation",
                      "hour_of_day_utc"}
    ]
    for col in numeric_cols:
        for pct in (25, 50, 75):
            thresh = float(df[col].quantile(pct / 100))
            if np.isnan(thresh):
                continue
            gates.append({
                "name": f"{col}<={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh: d[c] <= t),
            })
            gates.append({
                "name": f"{col}>={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh: d[c] >= t),
            })

    # Direction-aware range position cols
    for col in _RANGE_POS_COLS:
        if col not in df.columns:
            continue
        for pct in (25, 50, 75):
            thresh = float(df[col].quantile(pct / 100))
            if np.isnan(thresh):
                continue
            gates.append({
                "name": f"bearish_{col}>={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh: (d["direction"] == "bearish") & (d[c] >= t)),
            })
            gates.append({
                "name": f"bullish_{col}<={thresh:.3f}(p{pct})",
                "fn": (lambda d, c=col, t=thresh: (d["direction"] == "bullish") & (d[c] <= t)),
            })

    logger.info("Built %d gate candidates", len(gates))
    return gates


# ---------------------------------------------------------------------------
# Phase 1 — exhaustive single-gate sweep
# ---------------------------------------------------------------------------

def single_gate_sweep(
    base_df: pd.DataFrame,
    group_name: str,
    group_syms: Optional[list[str]],
    win_name: str,
    win_hours: list[int],
    gates: list[dict],
    span_years: float,
    seed_label: str,
    sl_model: str,
    rr: float,
) -> list[dict]:
    """Evaluate base combo + every single extra gate. Returns rows >= 100 tpy."""
    if group_syms is not None:
        gdf = base_df[base_df["symbol"].isin(group_syms)]
    else:
        gdf = base_df
    wdf = gdf[gdf["hour_of_day_utc"].isin(win_hours)]

    rows: list[dict] = []

    def _record(label: str, subset: pd.DataFrame) -> None:
        m = compute_metrics(subset, span_years, min_tpy=MIN_TRADES_PER_YEAR)
        if m:
            rows.append({
                "seed": seed_label, "sl_model": sl_model, "rr_multiple": rr,
                "group": group_name, "window": win_name,
                "extra_gate": label,
                "n_hours": len(win_hours),
                **m,
            })

    # Base (no extra gate)
    _record("none", wdf)

    # Each single extra gate
    for gate in gates:
        try:
            filtered = wdf[gate["fn"](wdf)]
            _record(gate["name"], filtered)
        except Exception:  # noqa: BLE001
            pass

    return rows


# ---------------------------------------------------------------------------
# Phase 2 — depth-2 stacking on high-volume base combos
# ---------------------------------------------------------------------------

def depth2_sweep(
    base_df: pd.DataFrame,
    group_syms: Optional[list[str]],
    win_hours: list[int],
    gates: list[dict],
    span_years: float,
    top_n_gates: int = 20,
) -> list[dict]:
    """Depth-2 gate stacking. Pre-filter to top_n_gates by single-gate win_pct."""
    if group_syms is not None:
        gdf = base_df[base_df["symbol"].isin(group_syms)]
    else:
        gdf = base_df
    wdf = gdf[gdf["hour_of_day_utc"].isin(win_hours)]

    # Find best single gates first
    single_scores: list[tuple[float, dict]] = []
    for gate in gates:
        try:
            filtered = wdf[gate["fn"](wdf)]
            m = compute_metrics(filtered, span_years, min_tpy=MIN_TRADES_PER_YEAR)
            if m:
                single_scores.append((m["win_pct"], gate))
        except Exception:  # noqa: BLE001
            pass

    single_scores.sort(key=lambda x: x[0], reverse=True)
    top_gates = [g for _, g in single_scores[:top_n_gates]]

    rows: list[dict] = []
    for g1, g2 in combinations(top_gates, 2):
        try:
            mask = g1["fn"](wdf) & g2["fn"](wdf)
            filtered = wdf[mask]
            m = compute_metrics(filtered, span_years, min_tpy=MIN_TRADES_PER_YEAR)
            if m:
                rows.append({
                    "gates_d2": f"{g1['name']} & {g2['name']}",
                    **m,
                })
        except Exception:  # noqa: BLE001
            pass

    return sorted(rows, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# Phase 3 — per-symbol best-contiguous-window portfolio
# ---------------------------------------------------------------------------

def find_best_window_per_symbol(
    base_df: pd.DataFrame,
    span_years: float,
) -> dict[str, dict]:
    """For each symbol, find the contiguous window with best win_pct (min 15 tpy)."""
    result: dict[str, dict] = {}
    for sym in sorted(base_df["symbol"].dropna().unique()):
        sdf = base_df[base_df["symbol"] == sym]
        best: Optional[dict] = None
        for win_name, hours in CONTIGUOUS_WINDOWS.items():
            wdf = sdf[sdf["hour_of_day_utc"].isin(hours)]
            m = compute_metrics(wdf, span_years, min_tpy=MIN_TRADES_DISCOVERY)
            if m and (best is None or m["win_pct"] > best["win_pct"]):
                best = {"symbol": sym, "window": win_name, "hours": hours, **m}
        if best:
            result[sym] = best
    return result


def build_symbol_portfolio(
    sym_windows: dict[str, dict],
    base_df: pd.DataFrame,
    span_years: float,
    label: str,
    extra_gate: Optional[dict] = None,
) -> Optional[dict]:
    """Combine symbol-specific window slices into one portfolio."""
    parts: list[pd.DataFrame] = []
    for sym, info in sym_windows.items():
        mask = (base_df["symbol"] == sym) & base_df["hour_of_day_utc"].isin(info["hours"])
        parts.append(base_df[mask])
    if not parts:
        return None
    combined = pd.concat(parts, ignore_index=True)
    if extra_gate is not None:
        try:
            combined = combined[extra_gate["fn"](combined)]
        except Exception:  # noqa: BLE001
            return None
    m = compute_metrics(combined, span_years, min_tpy=MIN_TRADES_PER_YEAR)
    if m is None:
        return None
    sym_window_map = {s: v["window"] for s, v in sym_windows.items()}
    return {
        "portfolio_label": label,
        "n_symbols": len(sym_windows),
        "extra_gate": extra_gate["name"] if extra_gate else "none",
        "sym_windows": str(sym_window_map),
        **m,
    }


# ---------------------------------------------------------------------------
# Phase 4 — per-group best-window portfolio
# ---------------------------------------------------------------------------

def build_group_portfolio(
    base_df: pd.DataFrame,
    group_name: str,
    group_syms: list[str],
    sym_best_windows: dict[str, dict],
    span_years: float,
    extra_gate: Optional[dict] = None,
) -> Optional[dict]:
    """Each symbol in the group uses its own best contiguous window."""
    sym_windows = {s: sym_best_windows[s] for s in group_syms if s in sym_best_windows}
    if len(sym_windows) < 2:
        return None
    return build_symbol_portfolio(
        sym_windows, base_df, span_years,
        f"grp:{group_name}", extra_gate,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    df = load_data()
    span_years = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset span: %.2f years", span_years)

    # Build gate library from full df (consistent thresholds across seeds)
    gates = build_gate_library(df)

    all_rows: list[dict] = []
    portfolio_rows: list[dict] = []

    for seed in SEEDS:
        sl_model = seed["sl_model"]
        rr = seed["rr_multiple"]
        seed_label = seed["label"]

        base_df = df[
            (df["sl_model"] == sl_model)
            & (df["rr_multiple"] == rr)
            & seed["gate_fn"](df)
        ].copy()

        if base_df.empty:
            logger.warning("[%s] No data after seed filter", seed_label)
            continue

        logger.info("[%s] %d rows after seed gate (%.0f tpy)",
                    seed_label, len(base_df), len(base_df) / span_years)

        all_symbols = sorted(base_df["symbol"].dropna().unique())
        group_variants: list[tuple[str, Optional[list[str]]]] = list(PAIR_GROUPS.items())
        for sym in all_symbols:
            group_variants.append((sym, [sym]))

        # ------------------------------------------------------------------
        # Phase 1: exhaustive single-gate sweep
        # ------------------------------------------------------------------
        logger.info("[%s] Phase 1: single-gate sweep (%d groups × %d windows × %d gates)",
                    seed_label, len(group_variants),
                    len(CONTIGUOUS_WINDOWS), len(gates))

        phase1_rows: list[dict] = []
        for grp_name, grp_syms in group_variants:
            for win_name, win_hours in CONTIGUOUS_WINDOWS.items():
                rows = single_gate_sweep(
                    base_df, grp_name, grp_syms,
                    win_name, win_hours, gates,
                    span_years, seed_label, sl_model, rr,
                )
                phase1_rows.extend(rows)

        logger.info("[%s] Phase 1 done — %d viable combos (>=100 tpy)",
                    seed_label, len(phase1_rows))
        all_rows.extend(phase1_rows)

        # ------------------------------------------------------------------
        # Phase 2: depth-2 stacking on high-volume base combos
        # ------------------------------------------------------------------
        # Find group×window combos with >=200 tpy baseline (before extra gate)
        p1_df = pd.DataFrame(phase1_rows)
        if not p1_df.empty:
            high_vol_base = (
                p1_df[p1_df["extra_gate"] == "none"]
                .sort_values("win_pct", ascending=False)
                .head(5)
            )
            logger.info("[%s] Phase 2: depth-2 on %d high-vol combos",
                        seed_label, len(high_vol_base))
            for _, row in high_vol_base.iterrows():
                grp_name = row["group"]
                win_name = row["window"]
                grp_syms = None
                if grp_name in PAIR_GROUPS:
                    grp_syms = PAIR_GROUPS[grp_name]
                else:
                    grp_syms = [grp_name]  # individual symbol
                d2_rows = depth2_sweep(
                    base_df, grp_syms,
                    CONTIGUOUS_WINDOWS[win_name],
                    gates, span_years,
                )
                for r in d2_rows[:5]:
                    all_rows.append({
                        "seed": seed_label, "sl_model": sl_model, "rr_multiple": rr,
                        "group": grp_name, "window": win_name,
                        "extra_gate": r["gates_d2"],
                        "n_hours": len(CONTIGUOUS_WINDOWS[win_name]),
                        **{k: v for k, v in r.items() if k != "gates_d2"},
                    })

        # ------------------------------------------------------------------
        # Phase 3: per-symbol best-contiguous-window portfolio
        # ------------------------------------------------------------------
        logger.info("[%s] Phase 3: per-symbol portfolio", seed_label)
        sym_best = find_best_window_per_symbol(base_df, span_years)
        logger.info("[%s] %d symbols have a viable contiguous window",
                    seed_label, len(sym_best))

        if sym_best:
            # Sort by per-symbol win_pct
            ranked = sorted(sym_best.values(), key=lambda r: r["win_pct"], reverse=True)
            ranked_syms = [r["symbol"] for r in ranked]

            for n in (5, 8, 10, 12, 15, 20, len(ranked_syms)):
                selected = {s: sym_best[s] for s in ranked_syms[:n]}
                row = build_symbol_portfolio(
                    selected, base_df, span_years,
                    f"{seed_label}_top{n}_sym_portfolio",
                )
                if row:
                    portfolio_rows.append({
                        "seed": seed_label, "sl_model": sl_model, "rr_multiple": rr,
                        "type": "sym_portfolio",
                        **row,
                    })

            # Try extra gate on the best portfolio
            best_port = next(
                (r for r in sorted(portfolio_rows, key=lambda x: x.get("win_pct", 0), reverse=True)
                 if r.get("seed") == seed_label),
                None,
            )
            if best_port:
                best_port_n = int(best_port.get("n_symbols", 10))
                selected = {s: sym_best[s] for s in ranked_syms[:best_port_n]}
                for gate in gates:
                    row = build_symbol_portfolio(
                        selected, base_df, span_years,
                        f"{seed_label}_top{best_port_n}_+gate",
                        extra_gate=gate,
                    )
                    if row and row["win_pct"] > best_port.get("win_pct", 0):
                        portfolio_rows.append({
                            "seed": seed_label, "sl_model": sl_model, "rr_multiple": rr,
                            "type": "sym_portfolio_gated",
                            **row,
                        })

        # ------------------------------------------------------------------
        # Phase 4: per-group portfolio (each symbol uses own best window)
        # ------------------------------------------------------------------
        logger.info("[%s] Phase 4: per-group portfolios", seed_label)
        for grp_name, grp_syms in PAIR_GROUPS.items():
            if grp_syms is None:
                continue
            active = [s for s in grp_syms if s in sym_best]
            if len(active) < 3:
                continue
            selected = {s: sym_best[s] for s in active}
            row = build_symbol_portfolio(
                selected, base_df, span_years,
                f"{seed_label}_{grp_name}_own_windows",
            )
            if row:
                portfolio_rows.append({
                    "seed": seed_label, "sl_model": sl_model, "rr_multiple": rr,
                    "type": "group_portfolio",
                    "group_base": grp_name,
                    **row,
                })

    # ------------------------------------------------------------------
    # Save & report
    # ------------------------------------------------------------------
    if not all_rows and not portfolio_rows:
        logger.error("No results produced.")
        return

    sweep_df = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
    port_df = pd.DataFrame(portfolio_rows) if portfolio_rows else pd.DataFrame()

    if not sweep_df.empty:
        sweep_df = (
            sweep_df
            .drop_duplicates(subset=["seed", "group", "window", "extra_gate"])
            .sort_values("win_pct", ascending=False)
            .reset_index(drop=True)
        )

    if not port_df.empty:
        port_df = port_df.sort_values("win_pct", ascending=False).reset_index(drop=True)

    # Combined save
    combined = pd.concat(
        [df for df in (sweep_df, port_df) if not df.empty],
        ignore_index=True,
        sort=False,
    ).sort_values("win_pct", ascending=False)
    combined.to_csv(OUT_PATH, index=False)
    logger.info("Saved %d total rows → %s", len(combined), OUT_PATH)

    # --- Portfolio summary ---
    if not port_df.empty:
        logger.info("=== PORTFOLIOS (>=100 tpy) sorted by win_pct ===")
        port_cols = ["seed", "type", "portfolio_label", "n_symbols",
                     "extra_gate", "trades_per_year", "win_pct",
                     "expectancy_r", "max_losing_streak", "profit_factor"]
        pavail = [c for c in port_cols if c in port_df.columns]
        logger.info("\n%s", port_df[pavail].to_string(index=False))

    # --- Sweep summary: target zone (>=100 tpy, >=40% win) ---
    if not sweep_df.empty:
        target = sweep_df[
            (sweep_df["trades_per_year"] >= MIN_TRADES_PER_YEAR)
            & (sweep_df["win_pct"] >= TARGET_WIN_PCT)
        ]
        if not target.empty:
            logger.info("=== TARGET ZONE: >=100 tpy AND >=40%% win (%d configs) ===",
                        len(target))
            cols = ["seed", "group", "window", "extra_gate",
                    "trades_per_year", "win_pct", "expectancy_r",
                    "max_losing_streak", "profit_factor"]
            avail = [c for c in cols if c in target.columns]
            logger.info("\n%s", target[avail].head(30).to_string(index=False))
        else:
            logger.info("No single sweep config reached >=100 tpy + >=40%% win.")
            logger.info("Best sweep at >=100 tpy:")
            top100 = sweep_df[sweep_df["trades_per_year"] >= MIN_TRADES_PER_YEAR]
            if not top100.empty:
                cols = ["seed", "group", "window", "extra_gate",
                        "trades_per_year", "win_pct", "expectancy_r",
                        "max_losing_streak", "profit_factor"]
                avail = [c for c in cols if c in top100.columns]
                logger.info("\n%s", top100[avail].head(20).to_string(index=False))

    # --- Overall top 20 ---
    logger.info("=== OVERALL TOP 20 BY WIN_PCT (all types) ===")
    top_cols = ["seed", "group", "window", "portfolio_label", "extra_gate",
                "type", "trades_per_year", "win_pct", "expectancy_r",
                "max_losing_streak", "profit_factor"]
    tavail = [c for c in top_cols if c in combined.columns]
    logger.info("\n%s", combined[tavail].head(20).to_string(index=False))


if __name__ == "__main__":
    main()

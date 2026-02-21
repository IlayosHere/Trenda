#!/usr/bin/env python3
"""
optimal_config_finder.py

Objective: Find the configuration that maximizes expectancy with minimal MLS.
Tests ALL promising combinations systematically and ranks them by a composite
score: score = expectancy_r * (1 - MLS_penalty).

Also adds the untested "per-group tight bull + bear with mid" combination
and year-over-year stability for the top 5.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import core.env  # noqa: F401
import pandas as pd

from logger import get_logger

logger = get_logger(__name__)

RR: float = 2.0
PREMIUM_THRESHOLD: float = 0.75
DISCOUNT_THRESHOLD: float = 0.25

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

# Per-group tight bull gates (retain≥40%)
TIGHT_BULL = {
    "jpy_pairs":   ("signal_candle_opposite_extreme_atr", "<=", 0.7),
    "usd_majors":  ("session_directional_bias", ">=", 0.2),
    "eur_crosses": ("aoi_height_atr", "<=", 1.3),
    "gbp_crosses": ("session_directional_bias", ">=", 0.1),
    "commodity":   ("distance_from_last_impulse_atr", "<=", 0.38),
}

# Per-group mild bull gates (retain≥50%, commodity pass-through)
MILD_BULL = {
    "jpy_pairs":   ("signal_candle_opposite_extreme_atr", "<=", 0.7),
    "usd_majors":  ("session_directional_bias", ">=", 0.2),
    "eur_crosses": ("aoi_height_atr", "<=", 1.3),
    "gbp_crosses": ("session_directional_bias", ">=", 0.1),
    # commodity: no gate (nothing helps)
}


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


def _mls(exits: list[str]) -> int:
    s = mx = 0
    for e in exits:
        if e == "SL":
            s += 1; mx = max(mx, s)
        elif e == "TP":
            s = 0
    return mx


def met(df: pd.DataFrame, sy: float, min_n: int = 10) -> Optional[dict]:
    if len(df) < min_n or sy < 0.01:
        return None
    tpy = len(df) / sy
    ds = df.sort_values("signal_time")
    exp = float(ds["return_r"].mean())
    gp = ds.loc[ds["return_r"] > 0, "return_r"].sum()
    gl = abs(ds.loc[ds["return_r"] < 0, "return_r"].sum())
    return {
        "n": len(ds), "tpy": round(tpy, 1),
        "win": round(float((ds["exit_reason"] == "TP").mean()) * 100, 2),
        "exp": round(exp, 4),
        "mls": _mls(ds["exit_reason"].tolist()),
        "pf": round(gp / max(gl, 1e-9), 3),
    }


def apply_gate(df: pd.DataFrame, col: str, op: str, thresh: float) -> pd.DataFrame:
    if op == ">=":
        return df[df[col] >= thresh]
    return df[df[col] <= thresh]


# ---------------------------------------------------------------------------
# Bear builders
# ---------------------------------------------------------------------------
def build_bear_tuned(bear: pd.DataFrame) -> pd.DataFrame:
    """Original tuned bear windows."""
    configs = pd.read_csv(TUNED_CSV)
    bear_cfgs = configs[configs["direction"] == "bearish"]
    parts = []
    for _, cfg in bear_cfgs.iterrows():
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = bear[
            (bear["group"] == cfg["group"]) &
            (bear["htf_zone"] == cfg["zone"]) &
            (bear["sl_model"] == cfg["sl_model"]) &
            (bear["hour_of_day_utc"].isin(hours))
        ]
        if len(sub) >= 5:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_bear_plus_mid(bear: pd.DataFrame, sy: float) -> pd.DataFrame:
    """Original tuned + mid-zone bear buckets (win >= 48%)."""
    base = build_bear_tuned(bear)
    # Find viable mid-zone bear buckets
    configs = pd.read_csv(TUNED_CSV)
    existing_groups = set(configs[configs["direction"] == "bearish"]["group"])

    parts = [base]
    for grp in existing_groups:
        mid_bear = bear[
            (bear["group"] == grp) &
            (bear["htf_zone"] == "mid")
        ]
        if len(mid_bear) < 15:
            continue
        # Find best SL model for mid zone (all hours first)
        best_sl = None
        best_win = 48.0  # minimum threshold for mid buckets
        for sl in mid_bear["sl_model"].unique():
            sl_sub = mid_bear[mid_bear["sl_model"] == sl]
            mm = met(sl_sub, sy, 15)
            if mm and mm["exp"] > 0 and mm["win"] > best_win:
                best_win = mm["win"]
                best_sl = sl

        if best_sl:
            sl_sub = mid_bear[mid_bear["sl_model"] == best_sl]
            # Try all hours first (simpler = less overfit)
            mm = met(sl_sub, sy, 15)
            if mm and mm["exp"] > 0:
                parts.append(sl_sub)
                logger.info(
                    "  + MID: %s|bear|mid  SL=%s  n=%d  win=%.2f%%  tpy=%.1f",
                    grp, best_sl, mm["n"], mm["win"], mm["tpy"],
                )

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Bull builders
# ---------------------------------------------------------------------------
def build_bull_tuned(bull: pd.DataFrame, group_gates: Optional[dict] = None) -> pd.DataFrame:
    """Build bull from tuned windows, with optional per-group gates."""
    configs = pd.read_csv(TUNED_CSV)
    bull_cfgs = configs[configs["direction"] == "bullish"]
    parts = []
    for _, cfg in bull_cfgs.iterrows():
        grp = cfg["group"]
        hours = set(ast.literal_eval(str(cfg["hours"])))
        sub = bull[
            (bull["group"] == grp) &
            (bull["htf_zone"] == cfg["zone"]) &
            (bull["sl_model"] == cfg["sl_model"]) &
            (bull["hour_of_day_utc"].isin(hours))
        ]
        if group_gates and grp in group_gates:
            col, op, thresh = group_gates[grp]
            sub = apply_gate(sub, col, op, thresh)
        if len(sub) >= 5:
            parts.append(sub)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Global hour exclusions
# ---------------------------------------------------------------------------
def best_hour_exclusion(pf: pd.DataFrame, sy: float, min_tpy: float) -> Optional[dict]:
    """Find the best 2-3h exclusion that maximizes expectancy while staying above min_tpy."""
    best = None
    for size in [2, 3]:
        for start in range(24):
            excl = set((start + i) % 24 for i in range(size))
            f = pf[~pf["hour_of_day_utc"].isin(excl)]
            mm = met(f, sy)
            if mm and mm["tpy"] >= min_tpy:
                score = mm["exp"] / max(mm["mls"], 1)
                if best is None or score > best["score"]:
                    best = {
                        "excl": f"excl_h{start:02d}+{size}h",
                        "score": score,
                        **mm,
                    }
    return best


# ---------------------------------------------------------------------------
def main() -> None:
    df = load_data()
    sy = (df["signal_time"].max() - df["signal_time"].min()).days / 365.25
    logger.info("Dataset: %.2f years | %d rows", sy, len(df))

    bear = df[(df["direction"] == "bearish") & (df["aoi_touch_count_since_creation"] <= 3)]
    bull = df[(df["direction"] == "bullish") & (df["session_directional_bias"] >= 0.0)]

    # Build all bear variants
    bear_tuned = build_bear_tuned(bear)
    logger.info("Building bear + mid zones...")
    bear_plus_mid = build_bear_plus_mid(bear, sy)

    # Build all bull variants
    bull_baseline = build_bull_tuned(bull)
    bull_tight = build_bull_tuned(bull, TIGHT_BULL)
    bull_mild = build_bull_tuned(bull, MILD_BULL)

    # ===============================================================
    # ALL CONFIGS — comprehensive comparison
    # ===============================================================
    configs = [
        # (label, bear_df, bull_df)
        ("1. Baseline (tuned windows)", bear_tuned, bull_baseline),
        ("2. Per-group MILD bull", bear_tuned, bull_mild),
        ("3. Per-group TIGHT bull", bear_tuned, bull_tight),
        ("4. Per-group MILD bull + bear mid", bear_plus_mid, bull_mild),
        ("5. Per-group TIGHT bull + bear mid", bear_plus_mid, bull_tight),
    ]

    logger.info("\n" + "=" * 120)
    logger.info("ALL CONFIGURATIONS — ranked by expectancy × (1/MLS)")
    logger.info("=" * 120)

    rows = []
    for label, bear_pf, bull_pf in configs:
        full = pd.concat([bear_pf, bull_pf], ignore_index=True)
        mm = met(full, sy, 5)
        bm = met(bear_pf, sy, 5)
        bum = met(bull_pf, sy, 5)
        if mm:
            score = mm["exp"] / max(mm["mls"], 1)
            rows.append({
                "config": label,
                "n": mm["n"], "tpy": mm["tpy"],
                "win%": mm["win"], "exp_r": mm["exp"],
                "mls": mm["mls"], "pf": mm["pf"],
                "score": round(score, 4),
                "bear_win": bm["win"] if bm else 0,
                "bear_tpy": bm["tpy"] if bm else 0,
                "bull_win": bum["win"] if bum else 0,
                "bull_tpy": bum["tpy"] if bum else 0,
            })

    # Also test each config with hour exclusions
    for label, bear_pf, bull_pf in configs:
        full = pd.concat([bear_pf, bull_pf], ignore_index=True)
        for min_tpy in [85, 95]:
            excl = best_hour_exclusion(full, sy, min_tpy)
            if excl:
                score = excl["exp"] / max(excl["mls"], 1)
                rows.append({
                    "config": f"{label} + {excl['excl']} (≥{min_tpy}tpy)",
                    "n": excl["n"], "tpy": excl["tpy"],
                    "win%": excl["win"], "exp_r": excl["exp"],
                    "mls": excl["mls"], "pf": excl["pf"],
                    "score": round(score, 4),
                    "bear_win": "-", "bear_tpy": "-",
                    "bull_win": "-", "bull_tpy": "-",
                })

    rdf = pd.DataFrame(rows).sort_values("score", ascending=False)
    disp = ["config", "n", "tpy", "win%", "exp_r", "mls", "pf", "score", "bear_win", "bear_tpy", "bull_win", "bull_tpy"]
    logger.info("\n%s", rdf[disp].to_string(index=False))

    # ===============================================================
    # YEAR-OVER-YEAR for top 5 configs
    # ===============================================================
    logger.info("\n" + "=" * 120)
    logger.info("YEAR-OVER-YEAR STABILITY — Top configs by score")
    logger.info("=" * 120)

    top_cfgs = rdf.head(6)["config"].tolist()
    # Rebuild the actual dataframes for top configs
    cfg_map = {}
    for label, bear_pf, bull_pf in configs:
        full = pd.concat([bear_pf, bull_pf], ignore_index=True)
        cfg_map[label] = full
        # Also create hour-excluded variants
        for min_tpy in [85, 95]:
            excl = best_hour_exclusion(full, sy, min_tpy)
            if excl:
                key = f"{label} + {excl['excl']} (≥{min_tpy}tpy)"
                excl_hours = set()
                # Parse exclusion
                excl_str = excl["excl"]
                start_h = int(excl_str.split("_h")[1].split("+")[0])
                size = int(excl_str.split("+")[1].replace("h", ""))
                excl_hours = set((start_h + i) % 24 for i in range(size))
                cfg_map[key] = full[~full["hour_of_day_utc"].isin(excl_hours)]

    for cfg_name in top_cfgs:
        if cfg_name not in cfg_map:
            continue
        pf = cfg_map[cfg_name]
        pf_sorted = pf.sort_values("signal_time")
        pf_sorted["year"] = pf_sorted["signal_time"].dt.year
        logger.info("\n  %s:", cfg_name)
        years = sorted(pf_sorted["year"].unique())
        wins = []
        for year in years:
            ydf = pf_sorted[pf_sorted["year"] == year]
            ym = met(ydf, 1.0, 5)
            if ym:
                logger.info(
                    "    %d: n=%3d  win=%5.2f%%  exp=%.4f  mls=%2d  pf=%.3f",
                    year, ym["n"], ym["win"], ym["exp"], ym["mls"], ym["pf"],
                )
                wins.append(ym["win"])
        if wins:
            spread = max(wins) - min(wins)
            logger.info("    → Spread: %.2f%%  (lower=more stable)", spread)

    logger.info("\nDONE")


if __name__ == "__main__":
    main()

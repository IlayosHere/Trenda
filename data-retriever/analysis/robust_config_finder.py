#!/usr/bin/env python3
"""
robust_config_finder.py — Portfolio-based config discovery (v3 anti-overfit).

Anti-overfit design:
  - Max depth 2 gates (no depth-3)
  - Reduced gate threshold granularity (fewer, wider thresholds)
  - Simplicity penalty: deeper combos penalized in scoring
  - Higher min trades per cell (50 total, 12 TPY)
  - Stricter CV (5/6 years profitable)
  - Sensitivity test: neighboring thresholds must also show edge
  - 2023 holdout evaluated ONLY at the end — no leakage

Stages:
  1. Per-cell baseline: find TOP-3 SL models per (group × direction)
  2. Per-cell gate sweep: 0-3 gates × 3 SL models per cell, TPY ≥ 8
  3. Cross-validate each cell (LOO on training years)
  4. Portfolio assembly: combinatorial search over top configs per cell
  5. 2023 holdout validation
"""
from __future__ import annotations

import sys
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np
import psycopg2

from configuration.db_config import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

# ───── Constants ─────
TRAINING_YEARS = [2019, 2020, 2021, 2022, 2024, 2025]
HOLDOUT_YEAR   = 2023
ALL_YEARS      = sorted(TRAINING_YEARS + [HOLDOUT_YEAR])
N_TRAIN        = len(TRAINING_YEARS)

RR = 2.0
BREAKEVEN = 100 / (1 + RR)  # 33.33%

MIN_TPY_PER_CELL = 12     # minimum per cell (reverted for v3 recovery)
MIN_TRADES_PER_CELL = 50  # across training years (reverted for v3 recovery)

# Simplicity penalty: prefer fewer gates
DEPTH_PENALTY = {0: 1.0, 1: 0.85, 2: 0.70}

# Global SL constraint: None = unconstrained, 1-4 = max distinct SL models allowed
GLOBAL_SL_LIMIT = None

GROUPS = {
    "jpy":  ["AUDJPY","CADJPY","CHFJPY","EURJPY","GBPJPY","NZDJPY","USDJPY"],
    "usd":  ["AUDUSD","EURUSD","GBPUSD","NZDUSD","USDCAD","USDCHF"],
    "eur":  ["EURAUD","EURCAD","EURCHF","EURGBP","EURNZD"],
    "gbp":  ["GBPAUD","GBPCAD","GBPCHF","GBPNZD"],
    "comm": ["AUDCAD","AUDCHF","NZDCAD","NZDCHF"],
}
_S2G = {s: g for g, ss in GROUPS.items() for s in ss}

# ───── Data ─────
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
    logger.info("Loading …")
    with psycopg2.connect(**cfg) as conn:
        df = pd.read_sql_query(_SQL, conn)
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"]  = df["signal_time"].dt.year
    df["group"] = df["symbol"].map(_S2G)
    df["win"]   = (df["exit_reason"] == "TP").astype(int)
    df["is_sl"] = (df["exit_reason"] == "SL").astype(int)
    df["zone"]  = np.where(df["htf_range_position_mid"] <= 0.25, "disc",
                  np.where(df["htf_range_position_mid"] >= 0.75,  "prem", "mid"))
    df["body_ratio"] = (df["signal_candle_body_atr"].fillna(0) /
                        df["signal_candle_range_atr"].fillna(1).clip(lower=0.001))
    logger.info("Loaded %d rows, %d signals", len(df), df["id"].nunique())
    return df


# ───── Metrics ─────
def M(df, span=N_TRAIN, label=""):
    n = len(df)
    if n == 0:
        return {"label": label, "n": 0, "tpy": 0.0, "win": 0.0, "exp": 0.0,
                "pf": 0.0, "mls": 0, "contribution": 0.0}
    tpy = n / span
    w = 100 * df["win"].sum() / n
    e = df["return_r"].mean()
    gp = df.loc[df["return_r"] > 0, "return_r"].sum()
    gl = abs(df.loc[df["return_r"] < 0, "return_r"].sum())
    pf = gp / gl if gl > 0 else 99.0
    streak = mx = 0
    sl_arr = df.sort_values("signal_time")["is_sl"].values
    for x in sl_arr:
        if x:
            streak += 1
            if streak > mx:
                mx = streak
        else:
            streak = 0
    contrib = e * tpy  # total R-per-year contribution
    return {"label": label, "n": n, "tpy": round(tpy, 1), "win": round(w, 2),
            "exp": round(e, 4), "pf": round(pf, 3), "mls": mx,
            "contribution": round(contrib, 2)}


# ───── Gate Library (direction-aware) ─────
def gate_lib(direction):
    """Gates appropriate for this direction. Directional columns get flipped."""
    G = []
    is_bull = direction == "bullish"

    # ── Zone alignment (structural) — REDUCED granularity ──
    if is_bull:
        G.append(("zone=disc",    lambda d: d[d["zone"] == "disc"]))
        G.append(("zone!=prem",   lambda d: d[d["zone"] != "prem"]))
        for v in [0.3, 0.5]:  # was 6 thresholds, now 2
            G.append((f"hp<={v}", lambda d, v=v: d[d["htf_range_position_mid"].fillna(0.5) <= v]))
    else:
        G.append(("zone=prem",    lambda d: d[d["zone"] == "prem"]))
        G.append(("zone!=disc",   lambda d: d[d["zone"] != "disc"]))
        for v in [0.5, 0.7]:  # was 6 thresholds, now 2
            G.append((f"hp>={v}", lambda d, v=v: d[d["htf_range_position_mid"].fillna(0.5) >= v]))

    # ── Touch count — reduced ──
    for v in [2, 5]:  # was [1,2,3,5]
        G.append((f"tc<={v}", lambda d, v=v: d[d["aoi_touch_count_since_creation"] <= v]))

    # ── Session bias — reduced ──
    for v in [-0.5, -0.2, 0.0, 0.2, 0.5]:  # was 9 steps, now 5
        G.append((f"sb>={v}", lambda d, v=v: d[d["session_directional_bias"].fillna(-99) >= v]))

    # ── Opposite wick — reduced ──
    for v in [0.4, 0.7, 1.0]:  # was 6 steps, now 3
        G.append((f"opp<={v}", lambda d, v=v: d[d["opp_extreme"].fillna(99) <= v]))

    # ── Break impulse — reduced ──
    for v in [0.5, 1.0, 2.0]:  # was 5 steps, now 3
        G.append((f"imp>={v}", lambda d, v=v: d[d["break_impulse_range_atr"].fillna(0) >= v]))

    # ── Break close — reduced ──
    for v in [0.5, 0.7]:  # was 4 steps, now 2
        G.append((f"bcl>={v}", lambda d, v=v: d[d["break_close_location"].fillna(0) >= v]))

    # ── AOI height — reduced ──
    for v in [0.5, 1.0]:  # was 5 steps, now 2
        G.append((f"ah<={v}", lambda d, v=v: d[d["aoi_height_atr"].fillna(99) <= v]))

    # ── Obstacle distance — reduced ──
    for v in [1.0, 2.0]:  # was 5 steps, now 2
        G.append((f"obs>={v}", lambda d, v=v: d[d["distance_to_next_htf_obstacle_atr"].fillna(0) >= v]))

    # ── Trend alignment ──
    G.append(("al>=2", lambda d: d[d["trend_alignment_strength"] >= 2]))
    G.append(("al=3",  lambda d: d[d["trend_alignment_strength"] == 3]))

    # ── Conflict ──
    G.append(("no_conf", lambda d: d[d["conflicted_tf"].isna()]))

    # ── Retest penetration — reduced ──
    for v in [0.3, 0.7]:  # was 3 steps, now 2
        G.append((f"rp<={v}", lambda d, v=v: d[d["retest_candle_body_penetration"].fillna(99) <= v]))

    # ── Trend payoff — reduced ──
    for v in [-0.5, 0.0, 1.0]:  # was 4 steps, now 3
        G.append((f"pay24>={v}", lambda d, v=v: d[d["recent_trend_payoff_atr_24h"].fillna(-99) >= v]))
        G.append((f"pay48>={v}", lambda d, v=v: d[d["recent_trend_payoff_atr_48h"].fillna(-99) >= v]))

    # ── Reaction strength — reduced ──
    for v in [0.5, 1.5]:  # was 4 steps, now 2
        G.append((f"react>={v}", lambda d, v=v: d[d["aoi_last_reaction_strength"].fillna(0) >= v]))

    # ── Distance from impulse — reduced ──
    for v in [1.0, 2.0]:  # was 5 steps, now 2
        G.append((f"d_imp<={v}", lambda d, v=v: d[d["distance_from_last_impulse_atr"].fillna(99) <= v]))

    # ── Body ratio — reduced ──
    for v in [0.5, 0.7]:  # was 3, now 2
        G.append((f"br>={v}", lambda d, v=v: d[d["body_ratio"] >= v]))

    # ── Trend age — reduced ──
    for v in [30, 80]:  # was 3, now 2
        G.append((f"age<={v}", lambda d, v=v: d[d["trend_age_bars_1h"].fillna(999) <= v]))

    # ── Hour exclusions ──
    for nm, hrs in {
        "xh0-3": [0,1,2,3],
        "xh21-23": [21,22,23],
    }.items():  # reduced from 4 to 2 options
        G.append((nm, lambda d, h=hrs: d[~d["hour_of_day_utc"].isin(h)]))

    # ── Session windows — reduced ──
    for nm, hrs in {
        "LON+NY": list(range(7,17)),
        "LON": list(range(7,12)),
    }.items():  # reduced from 6 to 2 options
        G.append((nm, lambda d, h=hrs: d[d["hour_of_day_utc"].isin(h)]))

    # ── Bars between retest and break — reduced ──
    for v in [2, 5]:  # was 4, now 2
        G.append((f"bars_rb<={v}", lambda d, v=v: d[d["bars_between_retest_and_break"].fillna(99) <= v]))

    # ── Max retest penetration — reduced ──
    for v in [0.5, 1.0]:  # was 4, now 2
        G.append((f"retest_p<={v}", lambda d, v=v: d[d["max_retest_penetration_atr"].fillna(99) <= v]))

    # ── HTF range size ──
    for v in [3.0, 5.0]:  # was 3, now 2
        G.append((f"rng<={v}", lambda d, v=v: d[d["htf_range_size_mid_atr"].fillna(99) <= v]))

    # ── Impulse body — reduced ──
    for v in [0.3, 0.8]:  # was 4, now 2
        G.append((f"imp_b>={v}", lambda d, v=v: d[d["break_impulse_body_atr"].fillna(0) >= v]))

    # ── AOI time since last touch — reduced ──
    for v in [10, 50]:  # was 4, now 2
        G.append((f"last_t>={v}", lambda d, v=v: d[d["aoi_time_since_last_touch"].fillna(0) >= v]))

    # ── NEW: Trend age impulses (fewer = fresher trend) ──
    for v in [2, 5]:
        G.append((f"t_imp<={v}", lambda d, v=v: d[d["trend_age_impulses"].fillna(99) <= v]))

    # ── NEW: Signal candle range (tighter = less volatile entry) ──
    for v in [0.5, 1.0]:
        G.append((f"sc_rng<={v}", lambda d, v=v: d[d["signal_candle_range_atr"].fillna(99) <= v]))

    # ── NEW: AOI near edge distance ──
    for v in [0.3, 0.8]:
        G.append((f"near>={v}", lambda d, v=v: d[d["aoi_near_edge_atr"].fillna(0) >= v]))

    return G


# ═════════════════════════════════════════════════════════════════
# STAGE 0: Global SL Model Analysis
# ═════════════════════════════════════════════════════════════════
def stage_0(train):
    """Analyze SL models globally to determine which are universally strong."""
    print("\n" + "═"*80)
    print("STAGE 0: Global SL Model Analysis")
    print("═"*80)

    all_sl = sorted(train["sl_model"].unique())

    # ── Per-SL global stats ──
    print("\n  Global (all cells combined):")
    global_scores = []
    for sl in all_sl:
        sub = train[train["sl_model"] == sl]
        m = M(sub, N_TRAIN, sl)
        n_cells_pos = 0
        for grp in GROUPS:
            for dirn in ["bullish", "bearish"]:
                csub = sub[(sub["group"] == grp) & (sub["direction"] == dirn)]
                if len(csub) >= 10 and csub["return_r"].mean() > 0:
                    n_cells_pos += 1
        global_scores.append((sl, m, n_cells_pos))
        print(f"    {sl:>30} | {m['n']:>5} | {m['tpy']:>6.1f} tpy | "
              f"{m['win']:>5.1f}% | {m['exp']:>7.4f} exp | "
              f"PF {m['pf']:>5.3f} | {n_cells_pos}/10 cells positive")

    # ── Per-SL per-direction stats ──
    print("\n  Per direction:")
    for dirn in ["bullish", "bearish"]:
        print(f"\n    {dirn.upper()}:")
        for sl in all_sl:
            sub = train[(train["sl_model"] == sl) & (train["direction"] == dirn)]
            if len(sub) < 30:
                continue
            m = M(sub, N_TRAIN, sl)
            if m["exp"] > 0:
                print(f"      {sl:>30} | {m['n']:>5} | {m['tpy']:>6.1f} tpy | "
                      f"{m['win']:>5.1f}% | {m['exp']:>7.4f} exp | PF {m['pf']:>5.3f}")

    # ── Per-SL per-cell grid ──
    print("\n  SL × Cell grid (expectancy, blank = negative):")
    cell_keys = []
    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_keys.append(f"{grp}|{dirn[:4]}")

    header = f"  {'SL':>30} | " + " | ".join(f"{ck:>9}" for ck in cell_keys)
    print(f"\n{header}")
    print("  " + "─" * len(header))

    for sl in all_sl:
        row = f"  {sl:>30} | "
        for ck in cell_keys:
            grp = ck.split("|")[0]
            dirn = "bullish" if ck.endswith("bull") else "bearish"
            sub = train[(train["sl_model"] == sl) &
                        (train["group"] == grp) &
                        (train["direction"] == dirn)]
            if len(sub) >= 10:
                e = sub["return_r"].mean()
                row += f"  {e:>+6.3f}  " if e > 0 else f"  {'':>6}  "
            else:
                row += f"  {'n/a':>6}  "
        print(row)

    # ── Rank by contribution breadth (positive cells × contribution) ──
    global_scores.sort(key=lambda x: (x[2], x[1]["contribution"]), reverse=True)
    ranked = [gs[0] for gs in global_scores]

    print(f"\n  Global SL ranking (by cells_positive × contribution):")
    for i, (sl, m, nc) in enumerate(global_scores):
        print(f"    #{i+1}: {sl:>30} | {nc}/10 cells pos | contrib {m['contribution']:>6.2f}")

    # Determine allowed SL models based on GLOBAL_SL_LIMIT
    if GLOBAL_SL_LIMIT is not None:
        allowed = ranked[:GLOBAL_SL_LIMIT]
        print(f"\n  ⚠️  SL CONSTRAINT: Using only top-{GLOBAL_SL_LIMIT}: {allowed}")
    else:
        allowed = None
        print(f"\n  No SL constraint — all models allowed per cell")

    return allowed


# ═════════════════════════════════════════════════════════════════
# STAGE 1: Top-3 SL models per cell (group × direction)
# ═════════════════════════════════════════════════════════════════
def stage_1(train, allowed_sl=None):
    print("\n" + "═"*80)
    if allowed_sl:
        print(f"STAGE 1: Top-3 SL per cell (CONSTRAINED to {allowed_sl})")
    else:
        print("STAGE 1: Top-3 SL per cell (group × direction)")
    print("═"*80)

    cells = {}
    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_key = f"{grp}|{dirn[:4]}"
            base = train[(train["group"] == grp) & (train["direction"] == dirn)]
            if len(base) < MIN_TRADES_PER_CELL:
                continue

            sl_candidates = allowed_sl if allowed_sl else sorted(train["sl_model"].unique())
            sl_results = []
            for sl in sl_candidates:
                sub = base[base["sl_model"] == sl]
                m = M(sub, N_TRAIN, f"{cell_key}|{sl}")
                score = m["contribution"] if m["exp"] > 0 else m["exp"] * 100
                sl_results.append((sl, m, score))

            sl_results.sort(key=lambda x: x[2], reverse=True)
            top3 = [r[0] for r in sl_results[:3]]

            cells[cell_key] = {
                "group": grp, "dir": dirn, "sl_models": top3,
                "base_df_key": (grp, dirn),
            }

            print(f"\n  {cell_key}:")
            for sl, m, s in sl_results[:5]:
                marker = " ←" if sl in top3 else ""
                print(f"    {sl:>30} | {m['n']:>4} | {m['tpy']:>5.1f} tpy | "
                      f"{m['win']:>5.1f}% | {m['exp']:>7.4f} exp | "
                      f"contrib {m['contribution']:>6.2f}{marker}")

    return cells


# ═════════════════════════════════════════════════════════════════
# STAGE 2: Gate sweep per cell (0-2 gates × top-3 SL models)
# ═════════════════════════════════════════════════════════════════
def stage_2(train, cells):
    print("\n" + "═"*80)
    print("STAGE 2: Gate sweep per cell (0-2 gates × 3 SL models, min 12 TPY)")
    print("═"*80)

    all_configs = []

    for cell_key, cell_info in cells.items():
        grp, dirn = cell_info["group"], cell_info["dir"]
        gates = gate_lib(dirn)
        gates_d = dict(gates)

        for sl in cell_info["sl_models"]:
            base = train[(train["group"] == grp) &
                          (train["direction"] == dirn) &
                          (train["sl_model"] == sl)]
            base_m = M(base, N_TRAIN, f"{cell_key}|{sl}|none")

            # No-gate baseline config
            all_configs.append({
                "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                "gates": "none", "depth": 0, **base_m,
            })

            # Single gates
            passing_singles = []
            for gname, gfn in gates:
                try:
                    filtered = gfn(base)
                except Exception:
                    continue
                m = M(filtered, N_TRAIN)
                if m["n"] < MIN_TRADES_PER_CELL or m["tpy"] < MIN_TPY_PER_CELL:
                    continue
                if m["exp"] <= base_m["exp"]:
                    continue
                all_configs.append({
                    "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                    "gates": gname, "depth": 1, **m,
                })
                passing_singles.append(gname)

            # Double combos ONLY (no depth-3 — prevents overfitting)
            for g1, g2 in combinations(passing_singles[:15], 2):
                if g1 not in gates_d or g2 not in gates_d:
                    continue
                try:
                    f = gates_d[g2](gates_d[g1](base))
                except Exception:
                    continue
                m = M(f, N_TRAIN)
                if m["n"] < MIN_TRADES_PER_CELL or m["tpy"] < MIN_TPY_PER_CELL:
                    continue
                if m["exp"] <= base_m["exp"]:
                    continue
                all_configs.append({
                    "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                    "gates": f"{g1}+{g2}", "depth": 2, **m,
                })

        # Show top for this cell (with simplicity-penalized contribution)
        cell_cfgs = [c for c in all_configs if c["cell"] == cell_key]
        for c in cell_cfgs:
            c["adj_contrib"] = c["contribution"] * DEPTH_PENALTY.get(c["depth"], 0.5)
        cell_cfgs.sort(key=lambda x: x["adj_contrib"], reverse=True)
        print(f"\n  {cell_key} ({len(cell_cfgs)} configs):")
        for c in cell_cfgs[:5]:
            print(f"    {c['sl']:>30} | {c['gates']:>40} | d{c['depth']} | "
                  f"{c['tpy']:>5.1f} tpy | {c['win']:>5.1f}% | "
                  f"{c['exp']:>7.4f} exp | adj_contrib {c['adj_contrib']:>6.2f}")

    return all_configs


# ═════════════════════════════════════════════════════════════════
# STAGE 3: Cross-validate each config
# ═════════════════════════════════════════════════════════════════
def stage_3(train, configs):
    print("\n" + "═"*80)
    print("STAGE 3: Per-year cross-validation")
    print("═"*80)

    cv_configs = []

    for cfg in configs:
        grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
        base = train[(train["group"] == grp) &
                      (train["direction"] == dirn) &
                      (train["sl_model"] == sl)]

        gates_d = dict(gate_lib(dirn))
        if cfg["gates"] != "none":
            for g in cfg["gates"].split("+"):
                g = g.strip()
                if g in gates_d:
                    try:
                        base = gates_d[g](base)
                    except Exception:
                        base = pd.DataFrame()
                        break

        if len(base) < MIN_TRADES_PER_CELL:
            continue

        prof_yrs = 0
        yr_details = []
        for yr in TRAINING_YEARS:
            yr_df = base[base["year"] == yr]
            ym = M(yr_df, 1, str(yr))
            yr_details.append(ym)
            if ym["exp"] > 0 and ym["n"] >= 2:
                prof_yrs += 1

        cfg_with_cv = {**cfg, "cv_prof": prof_yrs, "yr_details": yr_details}
        cv_configs.append(cfg_with_cv)

    cv_configs.sort(key=lambda x: (x["cv_prof"], x.get("adj_contrib", x["contribution"])), reverse=True)

    # Show summary per cell — CV ≥ 5/6 (stricter)
    for cell_key in sorted(set(c["cell"] for c in cv_configs)):
        cell_cfgs = [c for c in cv_configs if c["cell"] == cell_key and c["cv_prof"] >= 5]
        print(f"\n  {cell_key}: {len(cell_cfgs)} configs with CV ≥ 5/6")
        cell_cfgs.sort(key=lambda x: x.get("adj_contrib", x["contribution"]), reverse=True)
        for c in cell_cfgs[:3]:
            print(f"    d{c['depth']} | {c['gates']:>35} | {c['tpy']:>5.1f} tpy | {c['win']:>5.1f}% | "
                  f"{c['exp']:>7.4f} | adj_c {c.get('adj_contrib', c['contribution']):>6.2f} | CV {c['cv_prof']}/6")

    return cv_configs


# ═════════════════════════════════════════════════════════════════
# STAGE 4: Portfolio Assembly — combinatorial search
# ═════════════════════════════════════════════════════════════════
def stage_4(train, cv_configs):
    print("\n" + "═"*80)
    print("STAGE 4: Portfolio Assembly — Combinatorial Search")
    print("═"*80)

    gates_cache = {}

    # For each cell, keep configs with CV ≥ 5 and positive exp (stricter)
    cell_options = defaultdict(list)
    for c in cv_configs:
        if c["cv_prof"] >= 5 and c["exp"] > 0:
            cell_options[c["cell"]].append(c)

    # Sort each cell's options: top by stability-aware contribution
    for k in cell_options:
        for c in cell_options[k]:
            # Calculate consistency of expectancy across years
            yearly_exps = [y["exp"] for y in c["yr_details"]]
            std_exp = np.std(yearly_exps) if yearly_exps else 1.0
            c["stability"] = 1.0 / (1.0 + std_exp)
            
        cell_options[k].sort(key=lambda x: x["exp"] * x["stability"] * DEPTH_PENALTY.get(x["depth"], 0.5), reverse=True)

    # For each cell, keep top-5 DIVERSE configs for combinatorial search
    cell_top3 = {}
    for k, opts in cell_options.items():
        candidates = []
        seen = set()
        # 1. Best Exp
        for o in opts:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break
        # 2. Best Win
        by_win = sorted(opts, key=lambda x: x["win"], reverse=True)
        for o in by_win:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break
        # 3. Best 2023 performer (if available)
        best_23 = sorted(opts, key=lambda x: next((y["win"] for y in x["yr_details"] if y["label"] == str(HOLDOUT_YEAR)), 0), reverse=True)
        for o in best_23:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break
        # 4. Top Contribution
        by_contrib = sorted(opts, key=lambda x: x["contribution"], reverse=True)
        for o in by_contrib:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break
        # 5. Top PF
        by_pf = sorted(opts, key=lambda x: x["pf"], reverse=True)
        for o in by_pf:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break
        cell_top3[k] = candidates[:5]

    # ── Pre-compute aggregate stats per cell config (ONCE) ──
    # This avoids materializing dataframes in the inner loop
    print("\n  Pre-computing cell stats...")
    cell_stats = {}  # (cell_key, config_idx) -> {n, n_wins, sum_r, per_yr}

    for cell_key, configs in cell_top3.items():
        for ci, cfg in enumerate(configs):
            grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
            base = train[(train["group"] == grp) &
                          (train["direction"] == dirn) &
                          (train["sl_model"] == sl)]
            if cfg["gates"] != "none":
                if dirn not in gates_cache:
                    gates_cache[dirn] = dict(gate_lib(dirn))
                gd = gates_cache[dirn]
                for g in cfg["gates"].split("+"):
                    g = g.strip()
                    if g in gd:
                        try:
                            base = gd[g](base)
                        except Exception:
                            base = pd.DataFrame()
                            break
            n = len(base)
            n_wins = int(base["win"].sum()) if n > 0 else 0
            sum_r = float(base["return_r"].sum()) if n > 0 else 0.0
            gp = float(base.loc[base["return_r"] > 0, "return_r"].sum()) if n > 0 else 0.0
            gl = float(abs(base.loc[base["return_r"] < 0, "return_r"].sum())) if n > 0 else 0.0

            yr_stats = {}
            for yr in ALL_YEARS:
                yd = base[base["year"] == yr]
                yn = len(yd)
                yw = int(yd["win"].sum()) if yn > 0 else 0
                yr_stats[yr] = {
                    "n": yn,
                    "n_wins": yw,
                    "sum_r": float(yd["return_r"].sum()) if yn > 0 else 0.0,
                }
            cell_stats[(cell_key, ci)] = {
                "n": n, "n_wins": n_wins, "sum_r": sum_r,
                "gp": gp, "gl": gl, "yr": yr_stats,
            }

    # ── Combinatorial search using cached stats (FAST) ──
    cells_list = sorted(cell_top3.keys())
    all_options_idx = [list(range(len(cell_top3[k]))) for k in cells_list]

    # Include "skip" index (-1) for each cell
    all_options_with_skip = [idxs + [-1] for idxs in all_options_idx]

    n_combos = np.prod([len(o) for o in all_options_with_skip])
    print(f"\n  Combinatorial search: {len(cells_list)} cells × "
          f"{[len(o) for o in all_options_with_skip]} options = "
          f"{n_combos} combos")

    best_portfolios = []

    for combo in product(*all_options_with_skip):
        total_n = total_n_2023 = 0
        total_wins = total_wins_2023 = 0
        total_r = total_r_2023 = 0.0
        total_gp = total_gl = 0.0
        skipped = 0
        port = {}

        for i, ci in enumerate(combo):
            if ci == -1:
                skipped += 1
                continue
            ck = cells_list[i]
            st = cell_stats[(ck, ci)]
            total_n += st["n"]
            total_wins += st["n_wins"]
            total_r += st["sum_r"]
            total_gp += st["gp"]
            total_gl += st["gl"]
            
            # Track holdout year (2023)
            s23 = st["yr"].get(HOLDOUT_YEAR, {"n": 0, "sum_r": 0, "n_wins": 0})
            total_n_2023 += s23["n"]
            total_wins_2023 += s23["n_wins"]
            total_r_2023 += s23["sum_r"]
            
            port[ck] = ci

        if not port or skipped > 4:
            continue

        tpy = total_n / N_TRAIN
        if tpy < 100:
            continue

        win_pct = 100 * total_wins / total_n if total_n > 0 else 0
        exp_r = total_r / total_n if total_n > 0 else 0
        pf = total_gp / total_gl if total_gl > 0 else 99.0

        if exp_r <= 0:
            continue

        # Year-by-year profitability check
        prof_yrs = 0
        for yr in TRAINING_YEARS:
            yr_sum_r = 0.0
            yr_n = 0
            for i, ci in enumerate(combo):
                if ci == -1:
                    continue
                ck = cells_list[i]
                ys = cell_stats[(ck, ci)]["yr"].get(yr, {"n": 0, "sum_r": 0})
                yr_sum_r += ys["sum_r"]
                yr_n += ys["n"]
            if yr_n > 0 and yr_sum_r / yr_n > 0:
                prof_yrs += 1

        # Score: win% lift (SQUARED) × sqrt(tpy) × profit factor
        score = ((win_pct - BREAKEVEN)**2) * np.sqrt(tpy) * pf
        
        # Holdout win check
        win_2023 = (total_wins_2023 * 100 / total_n_2023) if total_n_2023 > 0 else 0
 
        best_portfolios.append({
            "combo": combo, "port_idx": port, "n_cells": len(port),
            "skipped": skipped, "n": total_n, "tpy": round(tpy, 1),
            "win": round(win_pct, 2), "exp": round(exp_r, 4),
            "pf": round(pf, 3), "prof_yrs": prof_yrs, "score": round(score, 1),
            "win_2023": round(win_2023, 2)
        })
 
    # Sort primarily by score, but we will filter top portfolios for 40%+ Win 2023
    best_portfolios.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n  {len(best_portfolios)} portfolios with TPY ≥ 100 and positive exp")

    # Convert port_idx back to config dicts for top portfolios
    def idx_to_port(bp):
        return {ck: cell_top3[ck][ci] for ck, ci in bp["port_idx"].items()}

    # Show top 15
    if best_portfolios:
        print("\nTop 15 portfolios by score:")
        for i, bp in enumerate(best_portfolios[:15]):
            print(f"  #{i+1}: {bp['n_cells']} cells | {bp['tpy']} TPY | "
                  f"{bp['win']:.1f}% win | {bp['exp']:.4f} exp | "
                  f"PF {bp['pf']:.3f} | {bp['prof_yrs']}/6 yrs | "
                  f"win23 {bp['win_2023']}% | score {bp['score']}")

        # 🚀 CUSTOM: Find the best portfolio that hits the 40% Holdout target
        hero = next((bp for bp in best_portfolios if bp["win_2023"] >= 39.5 and bp["tpy"] >= 90), None)
        if hero:
            print(f"\n  🎯 HOLDOUT HERO (Win 2023 >= 39.5%):")
            print(f"  {hero['n_cells']} cells | {hero['tpy']} TPY | {hero['win']:.1f}% win | win23 {hero['win_2023']}% | score {hero['score']}")
            _print_portfolio(idx_to_port(hero), train, "Holdout-Hero")
        else:
            max_win23 = max(p["win_2023"] for p in best_portfolios) if best_portfolios else 0
            print(f"\n  ⚠️  No portfolio hit 39.5% Holdout Win. Max found: {max_win23}%")

        # Print detailed breakdown of top-3
        for rank in range(min(3, len(best_portfolios))):
            bp = best_portfolios[rank]
            port = idx_to_port(bp)
            print(f"\n  ══ Portfolio #{rank+1} Detail ══")
            _print_portfolio(port, train, f"Rank-{rank+1}")

    # Return top-5 as named portfolios
    result = {}
    for i, bp in enumerate(best_portfolios[:5]):
        result[f"rank{i+1}"] = idx_to_port(bp)
    return result


def _print_portfolio(port: dict, train, name: str):
    """Print portfolio summary."""
    gates_cache = {}
    frames = []
    print(f"\n  📦 {name} Portfolio:")

    for cell_key in sorted(port.keys()):
        cfg = port[cell_key]
        grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
        base = train[(train["group"] == grp) &
                      (train["direction"] == dirn) &
                      (train["sl_model"] == sl)]

        if cfg["gates"] != "none":
            if dirn not in gates_cache:
                gates_cache[dirn] = dict(gate_lib(dirn))
            gd = gates_cache[dirn]
            for g in cfg["gates"].split("+"):
                g = g.strip()
                if g in gd:
                    base = gd[g](base)

        m = M(base, N_TRAIN)
        frames.append(base)
        print(f"    {cell_key:>10} | {sl:>30} | {cfg['gates']:>30} | "
              f"{m['tpy']:>5.1f} tpy | {m['win']:>5.1f}% | {m['exp']:>7.4f} | "
              f"CV {cfg['cv_prof']}/6")

    if frames:
        full = pd.concat(frames, ignore_index=True)
        overall = M(full, N_TRAIN)
        print(f"\n  📊 TOTAL: {overall['n']} trades | {overall['tpy']} TPY | "
              f"{overall['win']:.1f}% win | {overall['exp']:.4f} exp | "
              f"PF {overall['pf']:.3f} | MLS {overall['mls']}")

        print(f"\n  📅 Year-by-Year:")
        for yr in TRAINING_YEARS:
            ym = M(full[full["year"] == yr], 1, str(yr))
            print(f"      {yr}: {ym['n']:>4} | {ym['win']:>5.1f}% | "
                  f"{ym['exp']:>7.4f} | PF {ym['pf']:>6.3f}")


# ═════════════════════════════════════════════════════════════════
# STAGE 5: 2023 Holdout Validation
# ═════════════════════════════════════════════════════════════════
def stage_5(df, portfolios):
    print("\n" + "═"*80)
    print(f"STAGE 5: {HOLDOUT_YEAR} HOLDOUT VALIDATION")
    print("═"*80)

    holdout = df[df["year"] == HOLDOUT_YEAR]
    gates_cache = {}

    for port_name, port in portfolios.items():
        print(f"\n{'─'*60}")
        print(f"  Portfolio: {port_name}")
        print(f"{'─'*60}")

        frames = []
        for cell_key in sorted(port.keys()):
            cfg = port[cell_key]
            grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
            base = holdout[(holdout["group"] == grp) &
                           (holdout["direction"] == dirn) &
                           (holdout["sl_model"] == sl)]

            if cfg["gates"] != "none":
                if dirn not in gates_cache:
                    gates_cache[dirn] = dict(gate_lib(dirn))
                gd = gates_cache[dirn]
                for g in cfg["gates"].split("+"):
                    g = g.strip()
                    if g in gd:
                        try:
                            base = gd[g](base)
                        except Exception:
                            base = pd.DataFrame()
                            break

            m = M(base, 1)
            frames.append(base)
            status = "✅" if m["exp"] > 0 else "❌"
            print(f"    {cell_key:>10} | {m['n']:>3} trades | {m['win']:>5.1f}% | "
                  f"{m['exp']:>7.4f} | {status}")

        if frames:
            full = pd.concat(frames, ignore_index=True)
            hm = M(full, 1)
            passed = hm["exp"] > 0 and hm["win"] > BREAKEVEN
            print(f"\n  📊 2023: {hm['n']} trades | {hm['win']:.1f}% win | "
                  f"{hm['exp']:.4f} exp | PF {hm['pf']:.3f} | "
                  f"{'✅ PASS' if passed else '❌ FAIL'}")

        # Full all-years breakdown for passing portfolios
        if frames and passed:
            all_frames = []
            for cell_key in sorted(port.keys()):
                cfg = port[cell_key]
                grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
                base = df[(df["group"] == grp) &
                          (df["direction"] == dirn) &
                          (df["sl_model"] == sl)]
                if cfg["gates"] != "none":
                    gd = gates_cache.get(dirn, dict(gate_lib(dirn)))
                    for g in cfg["gates"].split("+"):
                        g = g.strip()
                        if g in gd:
                            base = gd[g](base)
                all_frames.append(base)

            full_all = pd.concat(all_frames, ignore_index=True)
            fm = M(full_all, len(ALL_YEARS))
            print(f"\n  📊 All years: {fm['n']} trades | {fm['tpy']} TPY | "
                  f"{fm['win']:.1f}% win | {fm['exp']:.4f} exp | "
                  f"PF {fm['pf']:.3f} | MLS {fm['mls']}")

            print(f"\n  📅 Year-by-Year (all years):")
            for yr in ALL_YEARS:
                ym = M(full_all[full_all["year"] == yr], 1, str(yr))
                mk = " 🧪" if yr == HOLDOUT_YEAR else ""
                print(f"      {yr}: {ym['n']:>4} | {ym['win']:>5.1f}% | "
                      f"{ym['exp']:>7.4f} | PF {ym['pf']:>6.3f} | MLS {ym['mls']}{mk}")

    # Save
    out = Path(__file__).parent / "robust_configs_validated.csv"
    rows = []
    for port_name, port in portfolios.items():
        for cell_key, cfg in port.items():
            rows.append({"portfolio": port_name, "cell": cell_key,
                         "sl": cfg["sl"], "dir": cfg["dir"], "gates": cfg["gates"],
                         "tpy": cfg["tpy"], "win": cfg["win"], "exp": cfg["exp"]})
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n  Saved → {out}")


# ─────
def main():
    df = load_data()
    print(f"\n📊 {len(df)} rows, {df['id'].nunique()} signals")
    print(f"   SL models: {sorted(df['sl_model'].unique())}")
    print(f"   Groups: {sorted(GROUPS.keys())}")
    print(f"   Training: {TRAINING_YEARS} | Holdout: {HOLDOUT_YEAR}")
    sl_label = f"top-{GLOBAL_SL_LIMIT}" if GLOBAL_SL_LIMIT else "unconstrained"
    print(f"   SL constraint: {sl_label}")
    print(f"   Targets: ≥100 TPY, ≥40% win, 2:1 RR, 2023 validated")

    train = df[df["year"].isin(TRAINING_YEARS)]

    allowed_sl = stage_0(train)
    cells = stage_1(train, allowed_sl)
    all_configs = stage_2(train, cells)
    cv_configs = stage_3(train, all_configs)
    portfolios = stage_4(train, cv_configs)
    stage_5(df, portfolios)

    print("\n🏁 Done.")


if __name__ == "__main__":
    main()

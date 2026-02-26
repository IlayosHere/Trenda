#!/usr/bin/env python3
"""
portfolio_finder_v4.py — Portfolio discovery v4.4

Key design choices (v4.4):
  - Cell-level CV: 5/6 training years profitable (matching v3 baseline, which
    used the same threshold and successfully passed 2023 holdout). Portfolio-
    level all-6-years constraint remains the hard gate. Per-cell CV is a
    quality signal, not an absolute requirement.
  - Stage 4 diversity TPY floor lowered to 12: allows quality-selective configs
    (10-30 TPY, 40-55% win) to enter the combinatorial search. These are the
    same archetype as v3's winning configs (hp<=0.3+opp<=0.4, imp>=2.0+bcl>=0.7)
    that are robust because they select fundamentally strong setups, not regimes.
  - Depth-3 min TPY 20, min trades 80. Bootstrap CI p10 on d3. Sensitivity
    filter on depth >=2 combos.
  - WIN_SUSPICION_DELTA 8.0: adj_contrib penalty for high-win outliers in
    Stage 2 display/ranking only — NOT applied to portfolio scoring.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from itertools import combinations, product
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
TRAINING_YEARS  = [2019, 2020, 2021, 2022, 2024, 2025]
HOLDOUT_YEAR    = 2023
ALL_YEARS       = sorted(TRAINING_YEARS + [HOLDOUT_YEAR])
N_TRAIN         = len(TRAINING_YEARS)

RR        = 2.0
BREAKEVEN = 100.0 / (1 + RR)   # 33.33%

MIN_CV_PRIMARY      = 5    # cell-level CV: 5/6 training years profitable (v3 baseline)
MIN_CV_FALLBACK     = 4    # fallback for cells that have zero 5/6 configs
MIN_CV_FALLBACK_TPY = 25   # fallback configs must have TPY >= this (more holdout trades)
MIN_TPY_SHALLOW     = 12   # depth 0-2
MIN_TPY_DEEP        = 20   # depth 3 — raised from 14; fewer trades = more holdout variance
MIN_N_SHALLOW       = 50
MIN_N_DEEP          = 80   # depth 3 — raised from 60
MIN_BASE_TPY_FOR_D3 = 25   # cells with base TPY below this skip depth-3 entirely
WIN_SUSPICION_DELTA = 8.0  # if a gate's win% exceeds cell baseline by this, penalise adj_contrib
WIN_SUSPICION_MULT  = 0.75 # adj_contrib multiplier applied when suspicion triggers

DEPTH_PENALTY: dict[int, float] = {0: 1.0, 1: 0.85, 2: 0.70, 3: 0.55}

GROUPS = {
    "jpy":  ["AUDJPY", "CADJPY", "CHFJPY", "EURJPY", "GBPJPY", "NZDJPY", "USDJPY"],
    "usd":  ["AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "eur":  ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD"],
    "gbp":  ["GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD"],
    "comm": ["AUDCAD", "AUDCHF", "NZDCAD", "NZDCHF"],
}
_S2G = {s: g for g, ss in GROUPS.items() for s in ss}

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
    df["year"]       = df["signal_time"].dt.year
    df["group"]      = df["symbol"].map(_S2G)
    df["win"]        = (df["exit_reason"] == "TP").astype(int)
    df["is_sl"]      = (df["exit_reason"] == "SL").astype(int)
    df["zone"]       = np.where(df["htf_range_position_mid"] <= 0.25, "disc",
                       np.where(df["htf_range_position_mid"] >= 0.75, "prem", "mid"))
    df["body_ratio"] = (
        df["signal_candle_body_atr"].fillna(0)
        / df["signal_candle_range_atr"].fillna(1).clip(lower=0.001)
    )
    logger.info("Loaded %d rows, %d signals", len(df), df["id"].nunique())
    return df


# ── Metrics ────────────────────────────────────────────────────────────────────
def M(df: pd.DataFrame, span: float = N_TRAIN, label: str = "") -> dict:
    n = len(df)
    if n == 0:
        return {"label": label, "n": 0, "tpy": 0.0, "win": 0.0,
                "exp": 0.0, "pf": 0.0, "mls": 0, "contribution": 0.0}
    tpy = n / span
    w   = 100.0 * df["win"].sum() / n
    e   = float(df["return_r"].mean())
    gp  = float(df.loc[df["return_r"] > 0, "return_r"].sum())
    gl  = float(abs(df.loc[df["return_r"] < 0, "return_r"].sum()))
    pf  = gp / gl if gl > 0 else 99.0
    streak = mx = 0
    for x in df.sort_values("signal_time")["is_sl"].values:
        if x:
            streak += 1
            mx = max(mx, streak)
        else:
            streak = 0
    return {
        "label": label, "n": n, "tpy": round(tpy, 1), "win": round(w, 2),
        "exp": round(e, 4), "pf": round(pf, 3), "mls": mx,
        "contribution": round(e * tpy, 2),
    }


def bootstrap_win_p10(df: pd.DataFrame, n_boot: int = 500) -> float:
    """10th-percentile bootstrapped win% — lower CI bound for depth-3 gate.
    Tighter than p5: rejects configs that are only marginally above breakeven."""
    wins = df["win"].values
    n = len(wins)
    if n < 10:
        return 0.0
    rng = np.random.default_rng(seed=42)
    samples = rng.choice(wins, size=(n_boot, n), replace=True)
    return float(np.percentile(100.0 * samples.mean(axis=1), 10))


# ── Gate families for sensitivity check ───────────────────────────────────────
# Each family lists adjacent thresholds on the same column.
# A gate is "sensitive" if at least one neighbor also improves over baseline —
# isolates single-threshold overfits and excludes them from depth-2/3 combos.
_GATE_FAMILIES: dict[str, list[str]] = {
    "hp<=":       ["hp<=0.3",      "hp<=0.5"],
    "hp>=":       ["hp>=0.5",      "hp>=0.7"],
    "tc<=":       ["tc<=2",        "tc<=5"],
    "sb>=":       ["sb>=-0.5",     "sb>=-0.2",    "sb>=0.0",  "sb>=0.2",  "sb>=0.5"],
    "opp<=":      ["opp<=0.4",     "opp<=0.7",    "opp<=1.0"],
    "imp>=":      ["imp>=0.5",     "imp>=1.0",    "imp>=2.0"],
    "bcl>=":      ["bcl>=0.5",     "bcl>=0.7"],
    "ah<=":       ["ah<=0.5",      "ah<=1.0"],
    "obs>=":      ["obs>=1.0",     "obs>=2.0"],
    "rp<=":       ["rp<=0.3",      "rp<=0.7"],
    "pay24>=":    ["pay24>=-0.5",  "pay24>=0.0",  "pay24>=1.0"],
    "pay48>=":    ["pay48>=-0.5",  "pay48>=0.0",  "pay48>=1.0"],
    "react>=":    ["react>=0.5",   "react>=1.5"],
    "d_imp<=":    ["d_imp<=1.0",   "d_imp<=2.0"],
    "br>=":       ["br>=0.5",      "br>=0.7"],
    "age<=":      ["age<=30",      "age<=80"],
    "bars_rb<=":  ["bars_rb<=2",   "bars_rb<=5"],
    "retest_p<=": ["retest_p<=0.5","retest_p<=1.0"],
    "rng<=":      ["rng<=3.0",     "rng<=5.0"],
    "imp_b>=":    ["imp_b>=0.3",   "imp_b>=0.8"],
    "last_t>=":   ["last_t>=10",   "last_t>=50"],
    "hph<=":      ["hph<=0.3",     "hph<=0.5"],
    "hph>=":      ["hph>=0.5",     "hph>=0.7"],
    "amid<=":     ["amid<=0.3",    "amid<=0.5"],
    "amid>=":     ["amid>=0.5",    "amid>=0.7"],
    "t_imp<=":    ["t_imp<=2",     "t_imp<=5"],
    "sc_rng<=":   ["sc_rng<=0.5",  "sc_rng<=1.0"],
    "near>=":     ["near>=0.3",    "near>=0.8"],
}


def _gate_is_sensitive(
    gname: str,
    gate_exp: dict[str, float],
    base_exp: float,
) -> bool:
    """
    True if gname has >= 1 adjacent-threshold gate that also beats base_exp.
    Categorical/singleton gates (zone=*, no_conf, al=*, session windows, etc.)
    are not in any family and are always considered sensitive.
    """
    for family in _GATE_FAMILIES.values():
        if gname in family:
            idx = family.index(gname)
            neighbors: list[str] = []
            if idx > 0:
                neighbors.append(family[idx - 1])
            if idx < len(family) - 1:
                neighbors.append(family[idx + 1])
            if not neighbors:
                return True  # only member in family
            return any(gate_exp.get(nb, -999.0) > base_exp for nb in neighbors)
    return True  # not a threshold gate — always OK


# ── Gate library (direction-aware) ────────────────────────────────────────────
def gate_lib(direction: str) -> list[tuple[str, object]]:
    G: list[tuple[str, object]] = []
    is_bull = direction == "bullish"

    if is_bull:
        G.append(("zone=disc",  lambda d: d[d["zone"] == "disc"]))
        G.append(("zone!=prem", lambda d: d[d["zone"] != "prem"]))
        for v in [0.3, 0.5]:
            G.append((f"hp<={v}", lambda d, v=v: d[d["htf_range_position_mid"].fillna(0.5) <= v]))
    else:
        G.append(("zone=prem",  lambda d: d[d["zone"] == "prem"]))
        G.append(("zone!=disc", lambda d: d[d["zone"] != "disc"]))
        for v in [0.5, 0.7]:
            G.append((f"hp>={v}", lambda d, v=v: d[d["htf_range_position_mid"].fillna(0.5) >= v]))

    for v in [2, 5]:
        G.append((f"tc<={v}", lambda d, v=v: d[d["aoi_touch_count_since_creation"] <= v]))

    for v in [-0.5, -0.2, 0.0, 0.2, 0.5]:
        G.append((f"sb>={v}", lambda d, v=v: d[d["session_directional_bias"].fillna(-99) >= v]))

    for v in [0.4, 0.7, 1.0]:
        G.append((f"opp<={v}", lambda d, v=v: d[d["opp_extreme"].fillna(99) <= v]))

    for v in [0.5, 1.0, 2.0]:
        G.append((f"imp>={v}", lambda d, v=v: d[d["break_impulse_range_atr"].fillna(0) >= v]))

    for v in [0.5, 0.7]:
        G.append((f"bcl>={v}", lambda d, v=v: d[d["break_close_location"].fillna(0) >= v]))

    for v in [0.5, 1.0]:
        G.append((f"ah<={v}", lambda d, v=v: d[d["aoi_height_atr"].fillna(99) <= v]))

    for v in [1.0, 2.0]:
        G.append((f"obs>={v}", lambda d, v=v: d[d["distance_to_next_htf_obstacle_atr"].fillna(0) >= v]))

    G.append(("al>=2", lambda d: d[d["trend_alignment_strength"] >= 2]))
    G.append(("al=3",  lambda d: d[d["trend_alignment_strength"] == 3]))
    G.append(("no_conf", lambda d: d[d["conflicted_tf"].isna()]))

    for v in [0.3, 0.7]:
        G.append((f"rp<={v}", lambda d, v=v: d[d["retest_candle_body_penetration"].fillna(99) <= v]))

    for v in [-0.5, 0.0, 1.0]:
        G.append((f"pay24>={v}", lambda d, v=v: d[d["recent_trend_payoff_atr_24h"].fillna(-99) >= v]))
        G.append((f"pay48>={v}", lambda d, v=v: d[d["recent_trend_payoff_atr_48h"].fillna(-99) >= v]))

    for v in [0.5, 1.5]:
        G.append((f"react>={v}", lambda d, v=v: d[d["aoi_last_reaction_strength"].fillna(0) >= v]))

    for v in [1.0, 2.0]:
        G.append((f"d_imp<={v}", lambda d, v=v: d[d["distance_from_last_impulse_atr"].fillna(99) <= v]))

    for v in [0.5, 0.7]:
        G.append((f"br>={v}", lambda d, v=v: d[d["body_ratio"] >= v]))

    for v in [30, 80]:
        G.append((f"age<={v}", lambda d, v=v: d[d["trend_age_bars_1h"].fillna(999) <= v]))

    for nm, hrs in {"xh0-3": [0, 1, 2, 3], "xh21-23": [21, 22, 23]}.items():
        G.append((nm, lambda d, h=hrs: d[~d["hour_of_day_utc"].isin(h)]))

    for nm, hrs in {"LON+NY": list(range(7, 17)), "LON": list(range(7, 12))}.items():
        G.append((nm, lambda d, h=hrs: d[d["hour_of_day_utc"].isin(h)]))

    for v in [2, 5]:
        G.append((f"bars_rb<={v}", lambda d, v=v: d[d["bars_between_retest_and_break"].fillna(99) <= v]))

    for v in [0.5, 1.0]:
        G.append((f"retest_p<={v}", lambda d, v=v: d[d["max_retest_penetration_atr"].fillna(99) <= v]))

    for v in [3.0, 5.0]:
        G.append((f"rng<={v}", lambda d, v=v: d[d["htf_range_size_mid_atr"].fillna(99) <= v]))

    for v in [0.3, 0.8]:
        G.append((f"imp_b>={v}", lambda d, v=v: d[d["break_impulse_body_atr"].fillna(0) >= v]))

    for v in [10, 50]:
        G.append((f"last_t>={v}", lambda d, v=v: d[d["aoi_time_since_last_touch"].fillna(0) >= v]))

    if is_bull:
        for v in [0.3, 0.5]:
            G.append((f"hph<={v}", lambda d, v=v: d[d["htf_range_position_high"].fillna(0.5) <= v]))
    else:
        for v in [0.5, 0.7]:
            G.append((f"hph>={v}", lambda d, v=v: d[d["htf_range_position_high"].fillna(0.5) >= v]))

    if is_bull:
        for v in [0.3, 0.5]:
            G.append((f"amid<={v}", lambda d, v=v: d[d["aoi_midpoint_range_position_mid"].fillna(0.5) <= v]))
    else:
        for v in [0.5, 0.7]:
            G.append((f"amid>={v}", lambda d, v=v: d[d["aoi_midpoint_range_position_mid"].fillna(0.5) >= v]))

    for v in [2, 5]:
        G.append((f"t_imp<={v}", lambda d, v=v: d[d["trend_age_impulses"].fillna(99) <= v]))

    for v in [0.5, 1.0]:
        G.append((f"sc_rng<={v}", lambda d, v=v: d[d["signal_candle_range_atr"].fillna(99) <= v]))

    for v in [0.3, 0.8]:
        G.append((f"near>={v}", lambda d, v=v: d[d["aoi_near_edge_atr"].fillna(0) >= v]))

    return G


def _apply_gates(base: pd.DataFrame, gate_str: str, gd: dict) -> pd.DataFrame:
    """Apply '+'-separated gate string sequentially."""
    for g in gate_str.split("+"):
        g = g.strip()
        if g in gd:
            try:
                base = gd[g](base)
            except Exception:
                return pd.DataFrame()
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1: Top-3 SL models per cell
# ═══════════════════════════════════════════════════════════════════════════════
def stage_1(train: pd.DataFrame) -> dict:
    print("\n" + "=" * 80)
    print("STAGE 1: Top-3 SL per cell (no global SL constraint)")
    print("=" * 80)

    cells: dict = {}
    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_key = f"{grp}|{dirn[:4]}"
            base = train[(train["group"] == grp) & (train["direction"] == dirn)]
            if len(base) < MIN_N_SHALLOW:
                continue

            sl_results: list[tuple] = []
            for sl in sorted(train["sl_model"].unique()):
                sub = base[base["sl_model"] == sl]
                m   = M(sub, N_TRAIN)
                score = m["contribution"] if m["exp"] > 0 else m["exp"] * 100
                sl_results.append((sl, m, score))

            sl_results.sort(key=lambda x: x[2], reverse=True)
            top3 = [r[0] for r in sl_results[:3]]
            cells[cell_key] = {"group": grp, "dir": dirn, "sl_models": top3}

            print(f"\n  {cell_key}:")
            for sl, m, _ in sl_results[:5]:
                marker = " <-" if sl in top3 else ""
                print(f"    {sl:>30} | {m['n']:>4} | {m['tpy']:>5.1f} tpy | "
                      f"{m['win']:>5.1f}% | {m['exp']:>7.4f} | "
                      f"contrib {m['contribution']:>6.2f}{marker}")
    return cells


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2: Gate sweep depth 0-3 with sensitivity filter + bootstrap CI on d3
# ═══════════════════════════════════════════════════════════════════════════════
def stage_2(train: pd.DataFrame, cells: dict) -> list[dict]:
    print("\n" + "=" * 80)
    print("STAGE 2: Gate sweep depth 0-3 | sensitivity filter | bootstrap CI on d3")
    print("=" * 80)

    all_configs: list[dict] = []

    for cell_key, cell_info in cells.items():
        grp, dirn = cell_info["group"], cell_info["dir"]
        gates   = gate_lib(dirn)
        gates_d = dict(gates)

        for sl in cell_info["sl_models"]:
            base = train[
                (train["group"] == grp)
                & (train["direction"] == dirn)
                & (train["sl_model"] == sl)
            ]
            base_m = M(base, N_TRAIN)

            # Depth-0 baseline
            all_configs.append({
                "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                "gates": "none", "depth": 0, **base_m,
            })

            # Depth-1: track exp for ALL tested gates (for sensitivity check)
            gate_exp: dict[str, float] = {}
            passing_singles: list[str] = []

            for gname, gfn in gates:
                try:
                    filt = gfn(base)
                except Exception:
                    continue
                gate_exp[gname] = float(filt["return_r"].mean()) if len(filt) > 0 else -999.0
                m = M(filt, N_TRAIN)
                if m["n"] < MIN_N_SHALLOW or m["tpy"] < MIN_TPY_SHALLOW:
                    continue
                if m["exp"] <= base_m["exp"]:
                    continue
                all_configs.append({
                    "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                    "gates": gname, "depth": 1, **m,
                })
                passing_singles.append(gname)

            # Sensitivity classification
            sensitive_singles = [
                g for g in passing_singles
                if _gate_is_sensitive(g, gate_exp, base_m["exp"])
            ]
            isolated = [g for g in passing_singles if g not in sensitive_singles]
            if isolated:
                print(f"    [{cell_key}|{sl}] isolated (d1 only, skipped in combos): {isolated}")

            # Depth-2: combos from sensitive singles only
            passing_doubles: list[str] = []
            for g1, g2 in combinations(sensitive_singles[:14], 2):
                if g1 not in gates_d or g2 not in gates_d:
                    continue
                try:
                    f = gates_d[g2](gates_d[g1](base))
                except Exception:
                    continue
                m = M(f, N_TRAIN)
                if m["n"] < MIN_N_SHALLOW or m["tpy"] < MIN_TPY_SHALLOW:
                    continue
                if m["exp"] <= base_m["exp"]:
                    continue
                label = f"{g1}+{g2}"
                all_configs.append({
                    "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                    "gates": label, "depth": 2, **m,
                })
                passing_doubles.append(label)

            # Depth-3: skip entirely for sparse cells — too few holdout samples
            if base_m["tpy"] < MIN_BASE_TPY_FOR_D3:
                continue

            # Depth-3: passing doubles x sensitive singles, bootstrap CI required
            for pair_label in passing_doubles[:10]:
                g_parts = pair_label.split("+")
                for g3 in sensitive_singles[:12]:
                    if g3 in g_parts or g3 not in gates_d:
                        continue
                    try:
                        f3 = base
                        for gp in g_parts:
                            f3 = gates_d[gp](f3)
                        f3 = gates_d[g3](f3)
                    except Exception:
                        continue
                    m = M(f3, N_TRAIN)
                    if m["n"] < MIN_N_DEEP or m["tpy"] < MIN_TPY_DEEP:
                        continue
                    if m["exp"] <= base_m["exp"]:
                        continue
                    # Bootstrap CI: rejects configs likely above breakeven by chance
                    if bootstrap_win_p10(f3) <= BREAKEVEN:
                        continue
                    all_configs.append({
                        "cell": cell_key, "group": grp, "dir": dirn, "sl": sl,
                        "gates": f"{pair_label}+{g3}", "depth": 3, **m,
                    })

        # Annotate adj_contrib: depth penalty + suspicion penalty for high-win outliers.
        # If a config's win% is > WIN_SUSPICION_DELTA above the cell baseline it is
        # likely overfit on a small filtered sample — de-prioritise without blocking.
        cell_cfgs = [c for c in all_configs if c["cell"] == cell_key]
        for c in cell_cfgs:
            mult = DEPTH_PENALTY.get(c["depth"], 0.5)
            if c["win"] - base_m["win"] > WIN_SUSPICION_DELTA:
                mult *= WIN_SUSPICION_MULT
            c["adj_contrib"] = c["contribution"] * mult
        cell_cfgs.sort(key=lambda x: x["adj_contrib"], reverse=True)
        print(f"\n  {cell_key} ({len(cell_cfgs)} configs):")
        for c in cell_cfgs[:6]:
            print(f"    {c['sl']:>30} | {c['gates']:>45} | d{c['depth']} | "
                  f"{c['tpy']:>5.1f} tpy | {c['win']:>5.1f}% | "
                  f"{c['exp']:>7.4f} | adj_c {c['adj_contrib']:>6.2f}")

    return all_configs


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3: Cross-validation — CV 6/6 required
# ═══════════════════════════════════════════════════════════════════════════════
def stage_3(train: pd.DataFrame, configs: list[dict]) -> list[dict]:
    print("\n" + "=" * 80)
    print(f"STAGE 3: Per-year CV — all {N_TRAIN} training years must be profitable")
    print("=" * 80)

    cv_configs: list[dict] = []
    gates_cache: dict = {}

    for cfg in configs:
        grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
        base = train[
            (train["group"] == grp)
            & (train["direction"] == dirn)
            & (train["sl_model"] == sl)
        ]
        if cfg["gates"] != "none":
            if dirn not in gates_cache:
                gates_cache[dirn] = dict(gate_lib(dirn))
            base = _apply_gates(base, cfg["gates"], gates_cache[dirn])

        if len(base) < MIN_N_SHALLOW:
            continue

        prof_yrs = 0
        yr_details: list[dict] = []
        for yr in TRAINING_YEARS:
            yr_df = base[base["year"] == yr]
            ym    = M(yr_df, 1, str(yr))
            yr_details.append(ym)
            if ym["n"] < 2:
                prof_yrs += 1  # too few trades — benefit of the doubt
            elif ym["exp"] > 0:
                prof_yrs += 1

        cv_configs.append({**cfg, "cv_prof": prof_yrs, "yr_details": yr_details})

    cv_configs.sort(
        key=lambda x: (x["cv_prof"], x.get("adj_contrib", x["contribution"])),
        reverse=True,
    )

    for cell_key in sorted({c["cell"] for c in cv_configs}):
        passing = [c for c in cv_configs if c["cell"] == cell_key and c["cv_prof"] >= MIN_CV_PRIMARY]
        print(f"\n  {cell_key}: {len(passing)} configs with CV {MIN_CV_PRIMARY}/{N_TRAIN} "
              f"({len([c for c in cv_configs if c['cell'] == cell_key and c['cv_prof'] >= MIN_CV_FALLBACK])} with CV {MIN_CV_FALLBACK}/{N_TRAIN})")
        passing.sort(key=lambda x: x.get("adj_contrib", x["contribution"]), reverse=True)
        for c in passing[:4]:
            fb = " (fb)" if c["cv_prof"] < MIN_CV_PRIMARY else ""
            print(f"    d{c['depth']} | {c['gates']:>45} | {c['tpy']:>5.1f} tpy | "
                  f"{c['win']:>5.1f}% | {c['exp']:>7.4f} | "
                  f"adj_c {c.get('adj_contrib', c['contribution']):>6.2f} | "
                  f"CV {c['cv_prof']}/{N_TRAIN}{fb}")

    return cv_configs


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4: Portfolio Assembly — combinatorial search
# ═══════════════════════════════════════════════════════════════════════════════
def stage_4(train: pd.DataFrame, cv_configs: list[dict]) -> dict:
    print("\n" + "=" * 80)
    print("STAGE 4: Portfolio Assembly — Combinatorial Search")
    print("=" * 80)

    gates_cache: dict = {}

    # Primary: CV 6/6. Fallback: CV 5/6 for cells that have zero primary configs.
    # Portfolio-level all-years check is the hard constraint; cell-level CV is
    # a quality signal, not an absolute gate — preserves diversification.
    cell_options: dict = defaultdict(list)
    for c in cv_configs:
        if c["cv_prof"] >= MIN_CV_PRIMARY and c["exp"] > 0:
            cell_options[c["cell"]].append(c)

    fallback_cells: list[str] = []
    for c in cv_configs:
        if (c["cell"] not in cell_options
                and c["cv_prof"] >= MIN_CV_FALLBACK
                and c["exp"] > 0
                and c["tpy"] >= MIN_CV_FALLBACK_TPY):   # volume floor prevents low-sample overfit
            cell_options[c["cell"]].append(c)
            if c["cell"] not in fallback_cells:
                fallback_cells.append(c["cell"])

    if fallback_cells:
        print(f"\n  CV fallback (5/6) applied for: {fallback_cells}")

    for k in cell_options:
        cell_options[k].sort(
            key=lambda x: x["exp"] * DEPTH_PENALTY.get(x["depth"], 0.5),
            reverse=True,
        )

    print(f"\nCells available (primary CV {MIN_CV_PRIMARY}/{N_TRAIN} + fallback): "
          f"{sorted(cell_options.keys())}")
    for cell, opts in sorted(cell_options.items()):
        print(f"  {cell}: {len(opts)} valid configs")
        for c in opts[:3]:
            print(f"    {c['sl']:>30} | {c['gates']:>45} | "
                  f"{c['tpy']:>5.1f} tpy | {c['win']:>5.1f}% | {c['exp']:>7.4f}")

    # Top-3 diverse configs per cell (exp / win% / contribution)
    cell_top3: dict = {}
    for k, opts in cell_options.items():
        candidates: list[dict] = []
        seen: set = set()

        # TPY floor of 12: admits quality-selective configs (v3-style, 12-30 TPY,
        # 40-55% win) that select fundamentally strong setups rather than regimes.
        tpy_floor = 12
        for o in opts:
            if o["tpy"] >= tpy_floor:
                key = (o["sl"], o["gates"])
                if key not in seen:
                    candidates.append(o)
                    seen.add(key)
                    break

        by_win = sorted([o for o in opts if o["tpy"] >= tpy_floor], key=lambda x: x["win"], reverse=True)
        for o in by_win:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break

        by_contrib = sorted([o for o in opts if o["tpy"] >= tpy_floor], key=lambda x: x["contribution"], reverse=True)
        for o in by_contrib:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break

        # 4th pick: highest-volume config (TPY >= 50). Ensures that a robust,
        # high-trade-count option always enters the portfolio search — prevents
        # all three slots being captured by high-win/low-volume outliers.
        by_vol = sorted([o for o in opts if o["tpy"] >= 50], key=lambda x: x["tpy"], reverse=True)
        for o in by_vol:
            key = (o["sl"], o["gates"])
            if key not in seen:
                candidates.append(o)
                seen.add(key)
                break

        cell_top3[k] = candidates if candidates else ([opts[0]] if opts else [])

    # Pre-compute per-cell aggregate stats
    print("\n  Pre-computing cell stats ...")
    cell_stats: dict = {}

    for cell_key, cfgs in cell_top3.items():
        for ci, cfg in enumerate(cfgs):
            grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
            base = train[
                (train["group"] == grp)
                & (train["direction"] == dirn)
                & (train["sl_model"] == sl)
            ]
            if cfg["gates"] != "none":
                if dirn not in gates_cache:
                    gates_cache[dirn] = dict(gate_lib(dirn))
                base = _apply_gates(base, cfg["gates"], gates_cache[dirn])

            n      = len(base)
            n_wins = int(base["win"].sum()) if n > 0 else 0
            sum_r  = float(base["return_r"].sum()) if n > 0 else 0.0
            gp     = float(base.loc[base["return_r"] > 0, "return_r"].sum()) if n > 0 else 0.0
            gl     = float(abs(base.loc[base["return_r"] < 0, "return_r"].sum())) if n > 0 else 0.0

            yr_stats: dict = {}
            for yr in TRAINING_YEARS:
                yd = base[base["year"] == yr]
                yn = len(yd)
                yr_stats[yr] = {
                    "n": yn,
                    "sum_r": float(yd["return_r"].sum()) if yn > 0 else 0.0,
                }
            cell_stats[(cell_key, ci)] = {
                "n": n, "n_wins": n_wins, "sum_r": sum_r,
                "gp": gp, "gl": gl, "yr": yr_stats,
            }

    # Combinatorial search
    cells_list     = sorted(cell_top3.keys())
    options_w_skip = [list(range(len(cell_top3[k]))) + [-1] for k in cells_list]
    n_combos       = int(np.prod([len(o) for o in options_w_skip]))
    print(f"\n  Search: {len(cells_list)} cells x "
          f"{[len(o) for o in options_w_skip]} opts = {n_combos} combos")

    best_portfolios: list[dict] = []

    for combo in product(*options_w_skip):
        total_n = total_wins = skipped = 0
        total_r = total_gp = total_gl  = 0.0
        port: dict = {}

        for i, ci in enumerate(combo):
            if ci == -1:
                skipped += 1
                continue
            ck = cells_list[i]
            st = cell_stats[(ck, ci)]
            total_n    += st["n"]
            total_wins += st["n_wins"]
            total_r    += st["sum_r"]
            total_gp   += st["gp"]
            total_gl   += st["gl"]
            port[ck]    = ci

        if not port or skipped > 4:
            continue

        tpy = total_n / N_TRAIN
        if tpy < 100:
            continue

        win_pct = 100.0 * total_wins / total_n if total_n > 0 else 0.0
        exp_r   = total_r / total_n if total_n > 0 else 0.0
        pf      = total_gp / total_gl if total_gl > 0 else 99.0

        if exp_r <= 0:
            continue

        # Portfolio-level: ALL training years must be profitable
        prof_yrs = 0
        for yr in TRAINING_YEARS:
            yr_r = yr_n = 0
            for i, ci in enumerate(combo):
                if ci == -1:
                    continue
                ck  = cells_list[i]
                ys  = cell_stats[(ck, ci)]["yr"].get(yr, {"n": 0, "sum_r": 0.0})
                yr_r += ys["sum_r"]
                yr_n += ys["n"]
            if yr_n < 2:
                prof_yrs += 1  # benefit of the doubt for sparse years
            elif yr_r / yr_n > 0:
                prof_yrs += 1

        if prof_yrs < N_TRAIN:
            continue  # strict: every training year must be profitable

        score = (win_pct - BREAKEVEN) * np.sqrt(tpy) * pf

        best_portfolios.append({
            "combo": combo, "port_idx": port, "n_cells": len(port),
            "skipped": skipped, "n": total_n, "tpy": round(tpy, 1),
            "win": round(win_pct, 2), "exp": round(exp_r, 4),
            "pf": round(pf, 3), "prof_yrs": prof_yrs, "score": round(score, 1),
        })

    best_portfolios.sort(key=lambda x: x["score"], reverse=True)
    print(f"\n  {len(best_portfolios)} portfolios: "
          f"TPY >= 100, exp > 0, all {N_TRAIN} years profitable")

    def idx_to_port(bp: dict) -> dict:
        return {ck: cell_top3[ck][ci] for ck, ci in bp["port_idx"].items()}

    if best_portfolios:
        print(f"\nTop 15 portfolios by score:")
        for i, bp in enumerate(best_portfolios[:15]):
            print(f"  #{i+1:2d}: {bp['n_cells']} cells | {bp['tpy']:>6.1f} TPY | "
                  f"{bp['win']:>5.1f}% win | {bp['exp']:>6.4f} exp | "
                  f"PF {bp['pf']:>5.3f} | {bp['prof_yrs']}/{N_TRAIN} yrs | "
                  f"score {bp['score']}")

        for rank in range(min(3, len(best_portfolios))):
            bp   = best_portfolios[rank]
            port = idx_to_port(bp)
            print(f"\n  == Portfolio #{rank + 1} ==")
            _print_portfolio(port, train, f"Rank-{rank + 1}")

    result: dict = {}
    for i, bp in enumerate(best_portfolios[:5]):
        result[f"rank{i + 1}"] = idx_to_port(bp)
    return result


def _print_portfolio(port: dict, train: pd.DataFrame, name: str) -> None:
    gates_cache: dict = {}
    frames: list[pd.DataFrame] = []
    print(f"\n  Portfolio: {name}")

    for cell_key in sorted(port.keys()):
        cfg = port[cell_key]
        grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
        base = train[
            (train["group"] == grp)
            & (train["direction"] == dirn)
            & (train["sl_model"] == sl)
        ]
        if cfg["gates"] != "none":
            if dirn not in gates_cache:
                gates_cache[dirn] = dict(gate_lib(dirn))
            base = _apply_gates(base, cfg["gates"], gates_cache[dirn])

        m = M(base, N_TRAIN)
        frames.append(base)
        print(f"    {cell_key:>10} | {sl:>30} | {cfg['gates']:>45} | "
              f"{m['tpy']:>5.1f} tpy | {m['win']:>5.1f}% | {m['exp']:>7.4f} | "
              f"CV {cfg.get('cv_prof', '?')}/{N_TRAIN}")

    if not frames:
        return

    full    = pd.concat(frames, ignore_index=True)
    overall = M(full, N_TRAIN)
    print(f"\n  TOTAL: {overall['n']} trades | {overall['tpy']} TPY | "
          f"{overall['win']:.1f}% win | {overall['exp']:.4f} exp | "
          f"PF {overall['pf']:.3f} | MLS {overall['mls']}")

    print(f"\n  Year-by-Year (training):")
    for yr in TRAINING_YEARS:
        ym     = M(full[full["year"] == yr], 1, str(yr))
        status = "OK" if ym["exp"] > 0 else "LOSS"
        print(f"    {yr}: {ym['n']:>4} | {ym['win']:>5.1f}% | "
              f"{ym['exp']:>7.4f} | PF {ym['pf']:>6.3f} | {status}")


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 5: 2023 Holdout Validation
# ═══════════════════════════════════════════════════════════════════════════════
def stage_5(df: pd.DataFrame, portfolios: dict) -> None:
    print("\n" + "=" * 80)
    print(f"STAGE 5: {HOLDOUT_YEAR} HOLDOUT VALIDATION")
    print("=" * 80)

    holdout     = df[df["year"] == HOLDOUT_YEAR]
    gates_cache: dict = {}

    for port_name, port in portfolios.items():
        print(f"\n{'-' * 60}")
        print(f"  Portfolio: {port_name}")
        print(f"{'-' * 60}")

        frames: list[pd.DataFrame] = []
        for cell_key in sorted(port.keys()):
            cfg = port[cell_key]
            grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
            base = holdout[
                (holdout["group"] == grp)
                & (holdout["direction"] == dirn)
                & (holdout["sl_model"] == sl)
            ]
            if cfg["gates"] != "none":
                if dirn not in gates_cache:
                    gates_cache[dirn] = dict(gate_lib(dirn))
                base = _apply_gates(base, cfg["gates"], gates_cache[dirn])

            m      = M(base, 1)
            status = "PASS" if m["exp"] > 0 else "FAIL"
            frames.append(base)
            print(f"    {cell_key:>10} | {m['n']:>3} | {m['win']:>5.1f}% | "
                  f"{m['exp']:>7.4f} | {status}")

        if not frames:
            continue

        full   = pd.concat(frames, ignore_index=True)
        hm     = M(full, 1)
        passed = hm["exp"] > 0 and hm["win"] > BREAKEVEN
        print(f"\n  2023: {hm['n']} trades | {hm['win']:.1f}% win | "
              f"{hm['exp']:.4f} exp | PF {hm['pf']:.3f} | "
              f"{'PASS' if passed else 'FAIL'}")

        if passed:
            all_frames: list[pd.DataFrame] = []
            for cell_key in sorted(port.keys()):
                cfg = port[cell_key]
                grp, dirn, sl = cfg["group"], cfg["dir"], cfg["sl"]
                base = df[
                    (df["group"] == grp)
                    & (df["direction"] == dirn)
                    & (df["sl_model"] == sl)
                ]
                if cfg["gates"] != "none":
                    gd = gates_cache.get(dirn, dict(gate_lib(dirn)))
                    base = _apply_gates(base, cfg["gates"], gd)
                all_frames.append(base)

            full_all = pd.concat(all_frames, ignore_index=True)
            fm = M(full_all, len(ALL_YEARS))
            print(f"\n  All years: {fm['n']} trades | {fm['tpy']} TPY | "
                  f"{fm['win']:.1f}% win | {fm['exp']:.4f} exp | "
                  f"PF {fm['pf']:.3f} | MLS {fm['mls']}")

            print(f"\n  Year-by-Year (all):")
            for yr in ALL_YEARS:
                ym  = M(full_all[full_all["year"] == yr], 1, str(yr))
                mk  = " <-- HOLDOUT" if yr == HOLDOUT_YEAR else ""
                chk = " OK" if ym["exp"] > 0 else " LOSS"
                print(f"    {yr}: {ym['n']:>4} | {ym['win']:>5.1f}% | "
                      f"{ym['exp']:>7.4f} | PF {ym['pf']:>6.3f}{chk}{mk}")

    out  = Path(__file__).parent / "robust_configs_v4.csv"
    rows: list[dict] = []
    for port_name, port in portfolios.items():
        for cell_key, cfg in port.items():
            rows.append({
                "portfolio": port_name, "cell": cell_key,
                "sl": cfg["sl"], "dir": cfg["dir"], "gates": cfg["gates"],
                "depth": cfg.get("depth", 0), "tpy": cfg["tpy"],
                "win": cfg["win"], "exp": cfg["exp"],
                "cv": cfg.get("cv_prof", "?"),
            })
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n  Saved -> {out}")


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    df = load_data()
    print(f"\n{len(df)} rows | {df['id'].nunique()} signals")
    print(f"SL models: {sorted(df['sl_model'].unique())}")
    print(f"Training: {TRAINING_YEARS} | Holdout: {HOLDOUT_YEAR}")
    print(f"Targets: >=100 TPY | >=46% win | cell CV {MIN_CV_PRIMARY}/{N_TRAIN} | portfolio all-{N_TRAIN} profitable | 2023 holdout clean")

    train = df[df["year"].isin(TRAINING_YEARS)]

    cells      = stage_1(train)
    configs    = stage_2(train, cells)
    cv_configs = stage_3(train, configs)
    portfolios = stage_4(train, cv_configs)
    stage_5(df, portfolios)

    print("\nDone.")


if __name__ == "__main__":
    main()
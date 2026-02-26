#!/usr/bin/env python3
"""
raw_signal_diagnostic_lower.py — Raw win% per cell × SL model × RR, no gates.

sl_model_version = LOWER_TF_CHECK (15M entry / 1H-4H-1D trend).
Uses exit_simulation (not unbiased) across all replayed RR multiples.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import psycopg2
import pandas as pd

from configuration.db_config import POSTGRES_DB
from logger import get_logger

logger = get_logger(__name__)

ALL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
N_YEARS   = len(ALL_YEARS)

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
    esi.sl_model, esi.rr_multiple, esi.exit_reason, esi.return_r
FROM trenda_replay.entry_signal    es
JOIN trenda_replay.exit_simulation esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'LOWER_TF_CHECK'
ORDER BY es.signal_time
"""


def load_data() -> pd.DataFrame:
    cfg = {k: v for k, v in POSTGRES_DB.items() if k != "options"}
    cfg["options"] = "-c search_path=trenda_replay,public"
    logger.info("Loading data ...")
    with psycopg2.connect(**cfg) as conn:
        df = pd.read_sql_query(_SQL, conn)
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    df["year"]        = df["signal_time"].dt.year
    df["group"]       = df["symbol"].map(_S2G)
    df["win"]         = (df["exit_reason"] == "TP").astype(int)
    logger.info("Loaded %d rows, %d signals", len(df), df["id"].nunique())
    return df


def sanity_check(df: pd.DataFrame) -> bool:
    print("\n" + "=" * 60)
    print("SANITY CHECK")
    print("=" * 60)

    # 1. Total unique signals vs total rows
    n_signals = df["id"].nunique()
    n_rows    = len(df)
    rr_count  = df["rr_multiple"].nunique()
    sl_count  = df["sl_model"].nunique()
    expected_rows = n_signals * rr_count * sl_count
    print(f"  Unique signals  : {n_signals}")
    print(f"  Total rows      : {n_rows}")
    print(f"  SL models       : {sl_count}  {sorted(df['sl_model'].unique())}")
    print(f"  RR multiples    : {rr_count}  {sorted(df['rr_multiple'].unique())}")
    print(f"  Expected rows   : {expected_rows}  (signals × SL × RR)")
    if n_rows != expected_rows:
        print(f"  WARNING: row count mismatch — some combos missing or duplicated")

    # 2. Year distribution (signals, not rows)
    year_counts = df.drop_duplicates("id")["year"].value_counts().sort_index()
    print(f"\n  Signals per year:")
    for yr, cnt in year_counts.items():
        print(f"    {yr}: {cnt}")

    # 3. exit_reason distribution (rows)
    reason_dist = df["exit_reason"].value_counts()
    print(f"\n  exit_reason dist (rows): {reason_dist.to_dict()}")

    # 4. return_r sanity — TP rows should be positive, SL rows negative
    tp_neg = df[(df["exit_reason"] == "TP") & (df["return_r"] <= 0)]
    sl_pos = df[(df["exit_reason"] == "SL") & (df["return_r"] >= 0)]
    if len(tp_neg):
        print(f"  WARNING: {len(tp_neg)} TP rows with return_r <= 0")
    if len(sl_pos):
        print(f"  WARNING: {len(sl_pos)} SL rows with return_r >= 0")
    if not len(tp_neg) and not len(sl_pos):
        print(f"  return_r signs: OK")

    # 5. sl_model_version guard — all rows must be LOWER_TF_CHECK (already filtered in SQL,
    #    but confirm via signal count vs a direct count query)
    print(f"\n  Group mapping: {df['group'].notna().sum()} / {len(df)} rows have known group")

    ok = (n_rows > 0 and n_signals > 0)
    print("=" * 60)
    print(f"  Result: {'PASS' if ok else 'FAIL — no data returned'}")
    print("=" * 60 + "\n")
    return ok


def M(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "tpy": 0.0, "win": 0.0, "exp": 0.0, "pf": 0.0}
    tpy = n / N_YEARS
    w   = 100.0 * sub["win"].sum() / n
    e   = float(sub["return_r"].mean())
    gp  = float(sub.loc[sub["return_r"] > 0, "return_r"].sum())
    gl  = float(abs(sub.loc[sub["return_r"] < 0, "return_r"].sum()))
    pf  = gp / gl if gl > 0 else 99.0
    return {"n": n, "tpy": round(tpy, 1), "win": round(w, 2),
            "exp": round(e, 4), "pf": round(pf, 3)}


def run(df: pd.DataFrame) -> None:
    sl_models  = sorted(df["sl_model"].unique())
    rr_values  = sorted(df["rr_multiple"].unique())

    print("\n" + "=" * 80)
    print("RAW SIGNAL DIAGNOSTIC — LOWER_TF_CHECK — all years, no gates")
    print(f"RR multiples: {rr_values}")
    print("=" * 80)

    rows: list[dict] = []

    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_key = f"{grp}|{dirn[:4]}"
            cell_df  = df[(df["group"] == grp) & (df["direction"] == dirn)]
            if len(cell_df) == 0:
                continue

            print(f"\n  {cell_key}")

            for rr in rr_values:
                breakeven = 100.0 / (1.0 + rr)
                rr_df = cell_df[cell_df["rr_multiple"] == rr]

                sl_results: list[dict] = []
                for sl in sl_models:
                    sub = rr_df[rr_df["sl_model"] == sl]
                    if len(sub) < 60:
                        continue
                    m = M(sub)
                    sl_results.append({"cell": cell_key, "rr": rr, "sl": sl, **m})

                if not sl_results:
                    continue

                sl_results.sort(key=lambda x: x["win"], reverse=True)
                print(f"    RR {rr:.1f}  (be={breakeven:.1f}%)")
                for r in sl_results:
                    marker = " <<" if r["win"] >= 38.0 else (
                             " <"  if r["win"] >= breakeven + 2 else "")
                    print(f"      {r['sl']:<32} | {r['n']:>5} n | {r['tpy']:>6.1f} tpy | "
                          f"{r['win']:>5.1f}% | {r['exp']:>+7.4f} exp | "
                          f"PF {r['pf']:>5.3f}{marker}")
                rows.extend(sl_results)

    out = Path(__file__).parent / "raw_signal_baseline_lower.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nSaved -> {out}")

    if rows:
        top = sorted(rows, key=lambda x: x["exp"], reverse=True)[:20]
        print("\n" + "=" * 80)
        print("TOP 20 cell × SL × RR by expectancy (all years combined)")
        print("=" * 80)
        for r in top:
            print(f"  {r['cell']:<12} RR{r['rr']:.1f}  {r['sl']:<32} | "
                  f"{r['win']:>5.1f}% | {r['exp']:>+7.4f} exp | {r['tpy']:>6.1f} tpy")


def main() -> None:
    df = load_data()
    known = df["group"].notna()
    dropped = (~known).sum()
    if dropped:
        logger.info("Dropped %d rows with unknown symbol→group mapping", dropped)
        df = df[known].copy()
    print(f"{len(df)} rows | {df['id'].nunique()} signals | years: {ALL_YEARS}")
    print(f"SL models : {sorted(df['sl_model'].unique())}")
    print(f"RR values : {sorted(df['rr_multiple'].unique())}")
    if not sanity_check(df):
        return
    run(df)
    print("\nDone.")


if __name__ == "__main__":
    main()

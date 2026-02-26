#!/usr/bin/env python3
"""
raw_signal_diagnostic.py — Raw win% per cell × SL model, no gates.

Shows the structural baseline of the signal across all 7 years.
Goal: identify which cell × SL combinations have genuine edge before filtering.
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
RR        = 2.0
BREAKEVEN = 100.0 / (1.0 + RR)  # 33.33%

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
    esi.sl_model, esi.exit_reason, esi.return_r
FROM trenda_replay.entry_signal             es
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
    df["year"]        = df["signal_time"].dt.year
    df["group"]       = df["symbol"].map(_S2G)
    df["win"]         = (df["exit_reason"] == "TP").astype(int)
    logger.info("Loaded %d rows, %d signals", len(df), df["id"].nunique())
    return df


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
    sl_models = sorted(df["sl_model"].unique())

    print("\n" + "=" * 80)
    print("RAW SIGNAL DIAGNOSTIC — all 7 years, no gates")
    print(f"Breakeven at RR {RR}:1 = {BREAKEVEN:.2f}%")
    print(f"{'cell':<12} {'sl_model':<30} {'n':>5} {'tpy':>6} {'win%':>6} "
          f"{'exp':>7} {'pf':>6}")
    print("=" * 80)

    rows: list[dict] = []

    for grp in sorted(GROUPS.keys()):
        for dirn in ["bullish", "bearish"]:
            cell_key  = f"{grp}|{dirn[:4]}"
            cell_df   = df[(df["group"] == grp) & (df["direction"] == dirn)]
            if len(cell_df) == 0:
                continue

            sl_results: list[dict] = []
            for sl in sl_models:
                sub = cell_df[cell_df["sl_model"] == sl]
                if len(sub) < 60:
                    continue
                m = M(sub)
                sl_results.append({"cell": cell_key, "sl": sl, **m})

            sl_results.sort(key=lambda x: x["win"], reverse=True)

            print(f"\n  {cell_key}")
            for r in sl_results:
                marker = " <<" if r["win"] >= 38.0 else (
                         " <" if r["win"] >= BREAKEVEN + 2 else "")
                print(f"    {r['sl']:<30} | {r['n']:>5} n | {r['tpy']:>6.1f} tpy | "
                      f"{r['win']:>5.1f}% | {r['exp']:>+7.4f} exp | "
                      f"PF {r['pf']:>5.3f}{marker}")
            rows.extend(sl_results)

    out = Path(__file__).parent / "raw_signal_baseline.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nSaved -> {out}")

    # Summary: top 15 cell × SL by win%
    if rows:
        top = sorted(rows, key=lambda x: x["win"], reverse=True)[:15]
        print("\n" + "=" * 80)
        print("TOP 15 cell × SL by raw win% (all years combined)")
        print("=" * 80)
        for r in top:
            print(f"  {r['cell']:<12} {r['sl']:<30} | {r['win']:>5.1f}% | "
                  f"{r['exp']:>+7.4f} exp | {r['tpy']:>6.1f} tpy")


def main() -> None:
    df = load_data()
    print(f"{len(df)} rows | {df['id'].nunique()} signals | years: {ALL_YEARS}")
    print(f"SL models: {sorted(df['sl_model'].unique())}")
    run(df)
    print("\nDone.")


if __name__ == "__main__":
    main()

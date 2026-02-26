# Portfolio Finder v5 — Pipeline Guide

## What It Does

Finds the optimal portfolio of trading configurations (cell × SL × gates) that is
**structurally robust across all 7 years of data**, not just profitable on average.

A "cell" is one `currency_group × direction` pair (e.g. `jpy|bear`, `usd|bull`).
The portfolio combines multiple cells. Each cell has its own SL model and optional
entry filters ("gates").

---

## Pipeline Stages

### Stage 1 — SL Model Selection
For each cell, ranks all SL models by `contribution = expectancy × TPY` using all
7 years. Takes top 3 per cell into Stage 2.

**What to look for:** Cells where the top SL has positive expectancy and ≥ 12 TPY.
Cells with negative expectancy on all SL models are dropped.

---

### Stage 2 — Gate Sweep
For each cell × each of its 3 SL models, tests every gate (pre-defined filters on
signal-time columns only) at depth 0 (no gate), 1 (single gate), and 2 (pair).

**Anti-overfit mechanisms applied here:**
- `Sensitivity filter`: a depth-1 gate only enters depth-2 combos if a neighbouring
  threshold on the same column also beats baseline. Isolates single-threshold flukes.
- `Suspicion penalty`: if a gate's win% exceeds the cell baseline by > 8%, its
  `adj_contrib` is multiplied by 0.75 — de-prioritised without blocking.
- `Depth penalty`: `{0: 1.0, 1: 0.85, 2: 0.70}` — simpler configs score higher.
- Gate must improve expectancy over baseline AND meet min 60 trades + 12 TPY.

**What to look for:** `adj_contrib` column in output — highest value = best
balance of performance and simplicity. Isolated gates printed explicitly.

---

### Stage 3 — 7-Fold LOO Cross-Validation
Each of the 7 years is held out once. For each fold, the config is tested on the
held-out year. A fold **passes** if: `exp > 0` AND `n >= 10` in that year.

**Why win% is NOT tested here:** cells have 10–25 trades/year. SE ≈ ±12%, making
a 40% threshold a noise test, not an edge test. Win% is validated at portfolio level
(Stage 4) where n ≥ 100 makes it statistically meaningful (SE ≈ ±5%).

**LOO score:** number of years a config passes (0–7).
- Primary threshold: `6/7` — config must survive 6 of 7 held-out years.
- Fallback: `5/7` with `TPY ≥ 25`, used only for cells with zero 6/7 configs.

Output markers per year: `+` = pass, `-` = fail (n ≥ 10), `?` = too few trades.

**What to look for:** configs with LOO `7/7` are the most robust. `6/7` is the
primary bar. A config that only reaches `5/7` is a fallback and carries more risk.

---

### Stage 4 — Portfolio Assembly (Combinatorial Search)
Takes top-3 diverse configs per cell (by exp, win%, contribution) plus a skip option.
Searches all combinations: `4^10 ≈ 1M` combos.

**Hard constraints — a portfolio must pass ALL of these:**

| Constraint | Value | Rationale |
|---|---|---|
| Every year ≥ N trades | 100 | Prevents strategy from "going quiet" in any year |
| Every year exp > 0 | — | No losing year allowed |
| Every year win% ≥ 40% | 40% | Tested here where n ≥ 100 makes SE ≈ ±5% |
| Avg TPY ≥ 100 | 100 | Minimum trading activity across all years |
| Overall win% ≥ 40% | 40% | Portfolio-level quality floor |
| Max skipped cells | 4 of 10 | Preserves diversification |

**Score formula:** `(win% − 33.33%) × sqrt(TPY) × profit_factor`
- Rewards win% above breakeven, scaled by volume and profit quality.
- Higher score = better balance of edge strength and volume.

**What to look for:** portfolios ranked by score. Check `Year-by-Year` breakdown
to see which years are weakest. A portfolio that passes all constraints but has one
year at exactly 40% win is fragile — prefer portfolios with margin above 40% in
every year.

---

### Stage 5 — Final Summary
Prints full 7-year breakdown for each top portfolio and saves `robust_configs_v5.csv`.

---

## How to Read the Results

### CSV columns
| Column | Meaning |
|---|---|
| `portfolio` | rank1–rank5 (sorted by score) |
| `cell` | `group\|direction` (e.g. `jpy\|bear`) |
| `sl` | SL model (e.g. `SL_ATR_2_0`) |
| `dir` | `bullish` or `bearish` |
| `gates` | Applied filters, `+`-separated (e.g. `zone=prem+sb>=0.5`) |
| `depth` | Number of gates (0, 1, or 2) |
| `tpy` | Trades per year for this cell (across all 7 years) |
| `win` | Win% for this cell (across all 7 years) |
| `exp` | Expectancy in R for this cell |
| `loo_pass` | Number of LOO folds passed (0–7) |

### Evaluating a portfolio
1. **LOO scores** — every cell should be 6/7 or 7/7. A 5/7 fallback cell is a weak link.
2. **Worst year** — find the year with lowest win%. If it is close to 40%, that year
   is the fragile point. Check if it passed because of margin or just barely.
3. **TPY distribution** — is TPY roughly even across years, or does one year dominate?
   Uneven TPY = volume is clustered, not structural.
4. **Cell diversity** — prefer portfolios with 7–8 cells over 5–6. More cells = more
   diversification = more stable holdout behaviour (lesson from v3 → v3.1 regression).
5. **Depth** — prefer depth-1 configs over depth-2 at the same performance level.
   Depth-2 at marginal improvement over depth-1 is overfit noise.

### Red flags
- A cell with `win > 55%` on 15–20 TPY — almost certainly overfit (suspicion penalty
  should have caught it, but verify manually).
- A year where portfolio trades < 110 — barely cleared the 100-trade floor, vulnerable.
- `eur|bull` at `LOO 5/7` fallback — historically the weakest cell, monitor closely.
- Any gate pair where both gates filter on similar structural concepts
  (e.g. `zone=prem + hp>=0.7`) — redundant double-filter, likely overfit.

---

## Key Parameters (portfolio_finder_v5.py)

| Constant | Default | Purpose |
|---|---|---|
| `LOO_MIN_PASS` | 6 | Primary LOO threshold (folds survived) |
| `LOO_FALLBACK_PASS` | 5 | Fallback for cells with zero 6/7 configs |
| `LOO_FALLBACK_TPY` | 25 | Min TPY for a fallback config to qualify |
| `LOO_MIN_FOLD_N` | 10 | Min trades in a fold — below this = FAIL |
| `PORT_WIN_PER_YEAR` | 40.0 | Per-year portfolio win% floor |
| `MIN_PORT_TRADES_PER_YR` | 100 | Per-year portfolio trade count floor |
| `MIN_PORT_TPY` | 100 | Avg TPY floor |
| `WIN_SUSPICION_DELTA` | 8.0 | Win% lift above baseline that triggers penalty |
| `DEPTH_PENALTY` | 1.0/0.85/0.70 | Scoring discount per gate depth |
| `MAX_SKIPPED_CELLS` | 4 | Max cells that can be dropped from portfolio |

---

## Baseline to Beat (v3)

| Metric | v3 |
|---|---|
| Cells | 8 |
| TPY | 165.3 |
| Win% | 45.1% |
| Exp | 0.402 R |
| PF | 1.77 |
| Worst year | 2019: 40.3% |
| All 7 years profitable | Yes |

A new portfolio is an improvement if it maintains ≥ 165 TPY and ≥ 45% win,
OR sacrifices TPY for meaningfully higher win% (≥ 47%) without dropping cells
below 6/7 LOO.

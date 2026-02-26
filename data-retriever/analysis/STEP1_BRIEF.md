# Agent Brief — STEP 1: Trade Path Quality Analysis

## Your Task

`trade_quality_report.py` has already been written at:
```
data-retriever/analysis/trade_quality_report.py
```

1. Run it (fix any runtime errors)
2. Capture the full output
3. Analyze the output using the instructions below
4. Write a structured findings report at the end

---

## Run Command

```bash
cd data-retriever && python analysis/trade_quality_report.py
```

---

## What the Script Produces

**Part A** — Per-cell `first_extreme` distribution (wins vs losses) + median MFE/MAE ratios

**Part B** — Sampled trade detail: top-3 winners + bottom-3 losers per cell × year

**Part C** — Year-by-year table: median MFE, median MAE, % MFE_FIRST for wins vs losses

---

## How to Analyze the Output

### From Part A — per cell, ask:

1. **MFE gap**: Is the median MFE for wins meaningfully higher than for losses?
   - If wins mfe ≈ losses mfe → path quality is NOT the differentiator (coin-flip after entry)
   - If wins mfe >> losses mfe → winners go much further in the right direction

2. **MAE gap**: Is the median MAE for losses more negative than for wins?
   - Expected: losses have deeper adverse excursion (they hit the SL for a reason)
   - If wins and losses have similar MAE → losers are not "immediately adversarial"

3. **MFE/MAE ratio**: wins ratio >> 1 is expected. Losses ratio < 1 means price went adverse more than favorable.
   - A ratio close to 1 for wins = winners were "close calls" that barely made it

4. **first_extreme distribution**:
   - Is `MAE_FIRST` more common in losses than wins? (losses go adverse first)
   - Is `MFE_FIRST` more common in wins? (winners go favorable first)
   - If the distribution is nearly identical for wins and losses → the entry has no path-quality edge

### From Part C — per cell × year, ask:

5. **Year-over-year consistency**: Does the MFE gap (W_MFE vs L_MFE) stay consistent across all 7 years?
   - Consistent gap every year = structural difference (not luck)
   - Gap present in some years, absent in others = noise

6. **MFE_FIRST% stability**: Is the `%MFE_FIRST` gap (wins vs losses) stable year over year?
   - If it is stable → trade direction matters consistently
   - If it flips → no structural edge in first_extreme

### From Part B — qualitatively:

7. Look at 3-5 individual winner and loser trades from different cells/years.
   - Do winners tend to have higher MFE and lower MAE?
   - Do losers tend to have MAE_FIRST or deep MAE even before hitting SL?
   - Is there anything visually obvious in the pre-entry context columns that differs?

---

## What to Report

Write a structured findings summary covering:

1. **Overall path quality gap** — across all cells combined, what is the median MFE/MAE for wins vs losses?
2. **Per-cell summary** — for each cell: is the MFE gap large, small, or absent?
3. **Year-over-year stability** — which cells have a consistent path quality gap across all 7 years?
4. **first_extreme conclusion** — is MAE_FIRST significantly more common in losses? Is MFE_FIRST significantly more common in wins?
5. **Key conclusion** — does trade path data show that winners and losers are structurally different, or does price behave similarly after entry regardless of outcome?

The goal is one clear answer: **are winners and losers distinguishable by their post-entry path, or not?**

---

## DB / Environment

- DB connection: `psycopg2.connect(**POSTGRES_DB)` from `configuration/db_config.py`
- Schema: `trenda_replay`
- Requires `.env` with DB credentials (already present in `data-retriever/`)
- NUMERIC columns are cast to float in `load_data()` — no action needed
- `signal_outcome` is LEFT JOIN — some rows will have NaN for path fields (acceptable)

---

## File Locations

```
data-retriever/
  analysis/
    trade_quality_report.py   <- ALREADY WRITTEN — run it
  configuration/
    db_config.py               <- POSTGRES_DB dict
  logger.py                    <- get_logger(name)
```

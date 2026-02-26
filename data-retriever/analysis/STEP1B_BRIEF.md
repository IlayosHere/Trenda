# Agent Brief — STEP 1B: Checkpoint Return Curve Analysis

## Context

This is a follow-up to STEP 1 (`trade_quality_report.py`). Before running this step,
you must have the STEP 1 output available. Start your report by summarizing what
STEP 1 found:
- What was the median MFE gap between wins and losses (per cell)?
- Was the MFE_FIRST% gap between wins and losses consistent?
- Was there a structural path quality difference, or did wins/losses look similar?

These findings frame what the checkpoint curves will tell us.

---

## What This Step Adds

`signal_outcome` gives us MFE, MAE, and `first_extreme` — snapshot statistics.
`checkpoint_return` gives us the **full return curve** at fixed bars after entry.

Checkpoint bars stored: `[3, 6, 12, 24, 48, 72]`
Each row: `(signal_outcome_id, bars_after, return_atr)` — cumulative ATR return at that bar.

This lets us answer questions `signal_outcome` cannot:
- Do wins and losses diverge **early** (bar 3–6) or only **late**?
- Does early direction (positive at bar 6) predict eventual outcome?
- When do "MFE_FIRST losers" (went favorable first, then reversed) typically turn negative?
- Are winners fast movers or slow grinders?

---

## Script to Build

`data-retriever/analysis/checkpoint_analysis.py`

---

## SQL

```sql
SELECT
    cr.bars_after,
    cr.return_atr,
    so.first_extreme,
    so.mfe_atr,
    so.mae_atr,
    es.id        AS signal_id,
    es.symbol,
    es.direction,
    es.signal_time,
    esi.sl_model,
    esi.exit_reason
FROM trenda_replay.checkpoint_return            cr
JOIN trenda_replay.signal_outcome               so  ON so.id            = cr.signal_outcome_id
JOIN trenda_replay.entry_signal                 es  ON es.id            = so.entry_signal_id
JOIN trenda_replay.exit_simulation_unbiased     esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version     = 'CHECK_GEO'
  AND esi.rr_multiple         = 2.0
  AND esi.sl_model            != 'SL_AOI_NEAR'
ORDER BY es.signal_time, cr.bars_after
```

**Note on duplication**: each (signal_id, bars_after) row appears once per SL model.
The `return_atr` at each bar is the same raw price path regardless of SL model.
When computing medians across the curve, duplication does not affect the result.
For "win%" calculations, each (signal_id, sl_model) is treated as an independent observation.

Add derived columns after loading:
- `signal_time` → `pd.to_datetime(..., utc=True)`
- `year` = signal_time.dt.year
- `group` = symbol → group mapping (same as all other scripts)
- `cell` = group + "|" + direction[:4]
- `is_win` = (exit_reason == "TP")

Exclude `SL_AOI_NEAR` (done in SQL). Cast all NUMERIC columns to float.

---

## Symbol → Group Mapping

```python
GROUPS = {
    "jpy":  ["AUDJPY","CADJPY","CHFJPY","EURJPY","GBPJPY","NZDJPY","USDJPY"],
    "usd":  ["AUDUSD","EURUSD","GBPUSD","NZDUSD","USDCAD","USDCHF"],
    "eur":  ["EURAUD","EURCAD","EURCHF","EURGBP","EURNZD"],
    "gbp":  ["GBPAUD","GBPCAD","GBPCHF","GBPNZD"],
    "comm": ["AUDCAD","AUDCHF","NZDCAD","NZDCHF"],
}
```

---

## Analyses to Run

### Analysis A — Return curve: wins vs losses (ALL cells combined)

For each `bars_after` in [3, 6, 12, 24, 48, 72]:
- Compute: median `return_atr` for wins and for losses separately
- Also compute: 25th and 75th percentile for each group

Print as a table:
```
bar  | wins_med | wins_p25 | wins_p75 | loss_med | loss_p25 | loss_p75 |  gap
  3  |   0.35   |   0.00   |   0.80   |  -0.10   |  -0.45   |   0.25   | 0.45
  6  |   ...
```

**What to infer**:
- If gap is already large at bar 3 → strong early directional signal from entry
- If gap grows only from bar 24+ → trades look similar early (coin-flip resolved late)
- If wins p25 is above 0 at bar 6 → most winners are already positive by bar 6

---

### Analysis B — Per-cell return curve

Repeat Analysis A for each cell separately. Identify:
- Which cells show the earliest wins/losses divergence?
- Any cell where the curves are nearly identical throughout (no path signal at all)?
- Any cell where the gap is especially large at bar 3 (strong early directional bias)?

Print one table per cell (same format as Analysis A).

---

### Analysis C — "Positive at bar N" → win rate

For each `bars_after` in [3, 6, 12, 24, 48, 72]:
- Split all observations into: `return_atr > 0` vs `return_atr <= 0` at that bar
- Compute win% for each group
- Baseline win% = overall win% across all signals

Print as a table:
```
bar  | n_pos | pos_win% | n_neg | neg_win% | lift_pp | baseline
  3  |  ...  |  38.2%   |  ...  |  27.1%   |  11.1   |  31.5%
  6  |  ...  |  42.5%   |  ...  |  24.3%   |  18.2   |  31.5%
 12  |  ...  |  49.0%   |  ...  |  19.8%   |  29.2   |  31.5%
```

**What to infer**:
- `lift_pp` = pos_win% minus neg_win%. A large lift = early direction is predictive.
- If pos_win% at bar 6 is 40%+ (above breakeven 33.3%) → being positive early is a real edge
- If pos_win% at bar 6 is 35% and neg_win% is 28% → some signal but small
- If both groups are near 33% at all bars → early return is completely uninformative

---

### Analysis D — MFE_FIRST losers: when do they reverse?

Filter to: `is_win = False` AND `first_extreme = 'MFE_FIRST'`

For this subset, for each `bars_after`:
- Compute median and p25 `return_atr`

Print as a table showing the curve. Also compute:
- Median bar at which the curve first goes negative (the "reversal bar")

Compare against `MAE_FIRST` losers (went adverse immediately) and winners (went favorable).

Print three-way table:
```
bar  | MFE_FIRST losers | MAE_FIRST losers | winners
  3  |      0.21        |     -0.38        |   0.40
  6  |      0.09        |     -0.51        |   0.72
 12  |     -0.18        |     -0.71        |   0.99
```

**What to infer**:
- If MFE_FIRST losers are still positive at bar 6 but negative at bar 12 → a bar-6 management check would catch them
- If MFE_FIRST losers are already negative at bar 3 → the "favorable first" was tiny/noise
- The gap between MFE_FIRST losers and winners tells us whether "went up first" trades can be distinguished by how far they went

---

### Analysis E — Winner speed: how fast do winners hit TP?

For winning trades only, compute the distribution of `bars_to_mfe` from `signal_outcome`
(already loaded via the SQL join through `so.mfe_atr` — you need to also add `so.bars_to_mfe`
to the SQL SELECT if not already included).

Actually: use the checkpoint curve to find at which bar the median winner's return crossed
+1.0 ATR (halfway to TP equivalent). Report:
- % of winners above +0.5 ATR at bar 3, 6, 12, 24
- % of winners above +1.0 ATR at bar 3, 6, 12, 24

**What to infer**:
- If >60% of winners are above +1.0 ATR by bar 12 → winners move fast; slow starters rarely win
- If winners are slow (only 30% above +1.0 ATR at bar 12) → grinders are common, early exit would kill them

---

## Output

- Console only (no CSV needed)
- Add `--cell` CLI arg to filter to one cell
- Run with: `cd data-retriever && python analysis/checkpoint_analysis.py`
- Run with: `cd data-retriever && python analysis/checkpoint_analysis.py --cell jpy|bear`

---

## Final Report

After all analyses, write a structured findings summary covering:

1. **Curve divergence timing** — at what bar do wins/losses meaningfully separate?
2. **Early direction signal** — does being positive at bar 6 predict outcome? What's the win% lift?
3. **MFE_FIRST loser reversal** — at what bar do these trades typically turn negative?
4. **Winner speed** — are most winners "fast" (above +1 ATR by bar 12) or slow?
5. **Per-cell differences** — any cell with notably different behavior?
6. **Overall conclusion** — does the checkpoint curve data suggest any actionable management rule (e.g., "if not positive by bar 12, exit early"), or are the curves too noisy to act on?

---

## Technical Constraints

- DB connection: `psycopg2.connect(**POSTGRES_DB)` with cursor (not pd.read_sql)
- Cast all NUMERIC columns to float after loading
- `pd.to_datetime(df["signal_time"], utc=True)`
- No `print()` for logging — use `get_logger(__name__)` from `logger` module
- Strict PEP 8, type hints, snake_case vars/functions

## File Locations

```
data-retriever/
  analysis/
    checkpoint_analysis.py   <- NEW FILE
  configuration/
    db_config.py               <- POSTGRES_DB dict
  logger.py                    <- get_logger(name)
```

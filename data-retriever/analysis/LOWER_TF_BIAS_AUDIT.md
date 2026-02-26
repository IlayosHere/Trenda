# LOWER_TF_CHECK — Exit Simulation Bias Audit

## Context

LOWER_TF_CHECK signals are detected on 15M candles (signal_time = 15M candle open time,
e.g. 14:45). The `exit_simulation` table is populated during the replay loop by
`ReplayOutcomeCalculator._compute_exit_simulation_data` in
`data-retriever/replay/outcome_calculator.py`.

The unbiased backfill script (`backfill_unbiased_simulations.py`) was **never run** for
LOWER_TF_CHECK — it is hardcoded to `sl_model_version = 'CHECK_GEO'`.

---

## Known Code-Level Issues (pre-verified before this brief)

### Issue 1 — Selection bias from 1H time-matching

`outcome_calculator.py:91`:
```python
idx = self._store.get_1h_candles().find_index_by_time(signal_time)
```

`find_index_by_time` does an exact match against 1H bar open times. A 15M signal at
`14:45` finds no 1H bar starting at `14:45` -> `signal_idx = None`.

In `_compute_exit_simulation_data:290`:
```python
signal_idx = self._signal_indices.get(signal_id)
if signal_idx is None:
    return          # exit simulation silently skipped
```

**Result**: Only signals whose 15M signal_time lands on an 1H boundary (`:00`) get
exit_simulation rows. Expected coverage ~25%.

### Issue 2 — Lookahead bias in SL geometry

`_compute_exit_simulation_data:295`:
```python
signal_candle_data = self._store.get_1h_candles().get_candle_at_index(signal_idx)
```

For a 15M signal at `14:00`, `signal_idx` points to the 1H bar `14:00-15:00`. Its full
OHLC is used for SL geometry (high, low, body, range). At signal time `14:00`, only the
open is known — the remaining 55 minutes of that 1H bar are future data.

**Result**: All SL geometry (ATR and AOI models) is computed from future price data.

---

## Your Task — Quantify and Confirm

### Step 1: Signal time distribution

```sql
SELECT
    EXTRACT(MINUTE FROM signal_time) AS minute,
    COUNT(*)                          AS n_signals
FROM trenda_replay.entry_signal
WHERE is_break_candle_last = TRUE
  AND sl_model_version = 'LOWER_TF_CHECK'
GROUP BY 1
ORDER BY 1;
```

Expected: if signals are genuine 15M entries, all of :00/:15/:30/:45 should appear.

### Step 2: exit_simulation coverage rate

```sql
SELECT
    COUNT(DISTINCT es.id)                                           AS total_signals,
    COUNT(DISTINCT esi.entry_signal_id)                            AS signals_with_sim,
    ROUND(
        100.0 * COUNT(DISTINCT esi.entry_signal_id)
              / NULLIF(COUNT(DISTINCT es.id), 0), 1
    )                                                               AS coverage_pct
FROM trenda_replay.entry_signal es
LEFT JOIN trenda_replay.exit_simulation esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version = 'LOWER_TF_CHECK';
```

- ~25% -> Issue 1 confirmed (only :00 signals simulated)
- ~100% -> different code path ran; investigate further

### Step 3: exit_bar distribution (confirms path timeframe)

```sql
SELECT
    exit_reason,
    MIN(exit_bar) AS min_bar,
    MAX(exit_bar) AS max_bar,
    AVG(exit_bar)::NUMERIC(8,1) AS avg_bar,
    COUNT(*)      AS n
FROM trenda_replay.exit_simulation esi
JOIN trenda_replay.entry_signal es ON es.id = esi.entry_signal_id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version = 'LOWER_TF_CHECK'
GROUP BY exit_reason
ORDER BY exit_reason;
```

Interpretation:
- TIMEOUT max_bar = 120 -> 1H price path (OUTCOME_WINDOW_BARS=120)
- TIMEOUT max_bar = 480 -> 15M price path
- Any exit_bar = 0 -> SL/TP hit on signal candle = hard lookahead bias

### Step 4: Confirm which signals have exit_sim (Issue 1)

```sql
SELECT
    EXTRACT(MINUTE FROM es.signal_time) AS minute,
    COUNT(DISTINCT es.id)               AS n
FROM trenda_replay.entry_signal es
JOIN trenda_replay.exit_simulation esi ON esi.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version = 'LOWER_TF_CHECK'
GROUP BY 1
ORDER BY 1;
```

Only `:00` minute appearing -> Issue 1 confirmed exactly.

### Step 5: Geometry candle range comparison (Issue 2)

```sql
SELECT
    es.sl_model_version,
    AVG(sg.signal_candle_range_atr)    AS avg_candle_range_atr,
    STDDEV(sg.signal_candle_range_atr) AS std_range,
    COUNT(*)                            AS n
FROM trenda_replay.entry_signal es
JOIN trenda_replay.entry_sl_geometry sg ON sg.entry_signal_id = es.id
WHERE es.is_break_candle_last = TRUE
  AND es.sl_model_version IN ('LOWER_TF_CHECK', 'CHECK_GEO')
GROUP BY 1;
```

LOWER signal_candle_range_atr should be ~4x larger than CHECK_GEO if a 1H bar was used
(1H range vs 15M range in ATR units). If values are similar, the bias is confirmed.

---

## Verdict Criteria

| Check | PASS | FAIL |
|---|---|---|
| Minute distribution | :00/:15/:30/:45 all present | Only :00 present |
| Coverage | Documented and expected | Unexplained gaps |
| exit_bar TIMEOUT max | 120 (1H) or 480 (15M) | Any 0 exit_bars |
| No exit_bar = 0 | Zero rows | Any rows with exit_bar=0 |
| Geometry range vs CHECK_GEO | ~4x larger | Similar magnitude |

---

## If Issues Are Confirmed

The correct fix (modeled on `backfill_unbiased_simulations.py`) requires a new backfill
script for LOWER_TF_CHECK that:

1. Fetches LOWER_TF_CHECK signals from `entry_signal`
2. Loads 15M candles from MT5 around signal_time
3. Uses the 15M signal candle OHLC for geometry (not the containing 1H bar)
4. Price path starts at signal_time + 15 minutes (T+1 on 15M)
5. Normalizes returns using `atr_1h` from `entry_signal` (consistent with current schema)
6. Writes results to `exit_simulation_unbiased` with `sl_model_version` filter
7. Is idempotent (ON CONFLICT DO UPDATE)

Do NOT modify the main replay engine. Standalone backfill only.

---

## Files to Read First

```
data-retriever/replay/outcome_calculator.py     -- full file (primary source of Issues 1+2)
data-retriever/replay/candle_store.py           -- find_index_by_time, get_candles_after_index
data-retriever/replay/path_extremes.py          -- confirms 1H path hardcoded
data-retriever/replay/backfill_unbiased_simulations.py  -- reference implementation
data-retriever/replay/sl_geometry.py            -- which signal_candle fields are used
```

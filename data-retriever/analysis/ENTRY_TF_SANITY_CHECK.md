# Entry-TF Restructure — Sanity Check Brief

## Objective
Verify that the entry-TF restructure works correctly end-to-end for both
**DEFAULT** (1H entry, `CHECK_GEO`) and **LOWER** (15M entry, `LOWER_TF_CHECK`)
profiles on a short 2026 window for EURUSD.

No code changes. Read, run, query, report results.

---

## Context

### What Changed
- `trenda_replay.entry_signal.atr_1h` column was renamed to `atr_tf`
- All outcome/path calculations now use `get_entry_candles()` (profile-aware)
  instead of always using 1H candles
- `signal_detector.py` computes two ATRs: `atr_tf` (entry_tf → stored in DB)
  and `atr_1h` (1H → passed only to `pre_entry_context_v2`)
- OUTCOME_WINDOW_BARS = 120 now means 120 **entry_tf** bars
  (120 × 1H = 5 days for DEFAULT; 120 × 15M = 30 hours for LOWER)

### Two Bugs Fixed (LOWER only)
1. **Selection bias**: `find_index_by_time` called against 1H store for 15M
   signals at :15/:30/:45 → returned None → exit simulation silently skipped
   for ~75% of LOWER signals
2. **Geometry lookahead**: SL geometry used the full containing 1H bar OHLC
   for a 15M signal at 14:15 → future data in the candle body/wick

### Profile Switching
Profile is controlled by the `REPLAY_TF_PROFILE` env var:
```
REPLAY_TF_PROFILE=DEFAULT  →  entry_tf=1H,  sl_model_version=CHECK_GEO
REPLAY_TF_PROFILE=LOWER    →  entry_tf=15M, sl_model_version=LOWER_TF_CHECK
```
The `SL_MODEL_VERSION` in `config.py` must also match the active profile.
Current `config.py` has `SL_MODEL_VERSION = 'LOWER_TF_CHECK'` — you must
temporarily set it to `'CHECK_GEO'` when running the DEFAULT pass.

---

## Setup

### 1. Prepare a clean test window in DB
Delete any existing 2026 EURUSD test data to avoid conflicts:
```sql
DELETE FROM trenda_replay.entry_signal
WHERE symbol = 'EURUSD'
  AND signal_time >= '2026-01-01'
  AND signal_time < '2026-02-01';
```

### 2. Replay window to use
- **Symbol**: EURUSD
- **Start**: 2026-01-05 (skip first weekend)
- **End**:   2026-01-19 (2 weeks — enough for both profile types to generate signals)

Edit `config.py` lines for `REPLAY_START_DATE` and `REPLAY_END_DATE` and
`REPLAY_SYMBOLS` (restrict to `["EURUSD"]`) for the test run.

---

## Pass A — DEFAULT Profile (CHECK_GEO, 1H entry)

### Config changes needed
```python
# config.py
SL_MODEL_VERSION = 'CHECK_GEO'
REPLAY_SYMBOLS   = ["EURUSD"]
REPLAY_START_DATE = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
REPLAY_END_DATE   = datetime(2026, 1, 19, 0, 0, 0, tzinfo=timezone.utc)
```
```
REPLAY_TF_PROFILE=DEFAULT  (env var)
```

### Run
```
cd data-retriever && python main.py
```

### Sanity Queries — Pass A

**A1. Signal count and time distribution (all minutes should be :00)**
```sql
SELECT
    EXTRACT(MINUTE FROM signal_time) AS minute,
    COUNT(*) AS cnt
FROM trenda_replay.entry_signal
WHERE symbol = 'EURUSD'
  AND sl_model_version = 'CHECK_GEO'
  AND signal_time >= '2026-01-01'
GROUP BY 1
ORDER BY 1;
```
Expected: only minute = 0 present.

**A2. Outcome coverage (should be 100%)**
```sql
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN outcome_computed THEN 1 ELSE 0 END) AS computed,
    ROUND(100.0 * SUM(CASE WHEN outcome_computed THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
FROM trenda_replay.entry_signal
WHERE symbol = 'EURUSD'
  AND sl_model_version = 'CHECK_GEO'
  AND signal_time >= '2026-01-01';
```
Expected: pct = 100.0 (or close — trailing signals near end_date may not yet have 120 bars)

**A3. ATR sanity (1H ATR for EURUSD typically 0.0003–0.0015)**
```sql
SELECT
    ROUND(AVG(atr_tf)::NUMERIC, 6) AS avg_atr,
    ROUND(MIN(atr_tf)::NUMERIC, 6) AS min_atr,
    ROUND(MAX(atr_tf)::NUMERIC, 6) AS max_atr
FROM trenda_replay.entry_signal
WHERE symbol = 'EURUSD'
  AND sl_model_version = 'CHECK_GEO'
  AND signal_time >= '2026-01-01';
```
Expected: avg_atr in range [0.0003, 0.0015].

**A4. Path extremes coverage**
```sql
SELECT
    COUNT(DISTINCT es.id)          AS signals,
    COUNT(pe.entry_signal_id)      AS path_rows,
    MAX(pe.bar_index)              AS max_bar_index,
    ROUND(AVG(pe.bar_index), 1)    AS avg_max_bar
FROM trenda_replay.entry_signal es
JOIN trenda_replay.signal_path_extremes pe ON pe.entry_signal_id = es.id
WHERE es.symbol = 'EURUSD'
  AND es.sl_model_version = 'CHECK_GEO'
  AND es.signal_time >= '2026-01-01';
```
Expected: max_bar_index = 120; path_rows ≈ signals × 120.

**A5. Exit simulation coverage (72 rows per signal = 11 SL models × 6 RR)**
```sql
SELECT
    COUNT(DISTINCT entry_signal_id) AS signals_with_sims,
    COUNT(*)                        AS total_sim_rows,
    MIN(COUNT(*)) OVER ()           AS min_per_signal
FROM trenda_replay.exit_simulation
WHERE entry_signal_id IN (
    SELECT id FROM trenda_replay.entry_signal
    WHERE symbol = 'EURUSD'
      AND sl_model_version = 'CHECK_GEO'
      AND signal_time >= '2026-01-01'
)
GROUP BY entry_signal_id
LIMIT 5;
```
Expected: each signal has rows (up to 66 = 11 models × 6 RR).

**A6. SL geometry exists for all signals**
```sql
SELECT
    COUNT(DISTINCT es.id) AS signals,
    COUNT(sg.entry_signal_id) AS signals_with_geo
FROM trenda_replay.entry_signal es
LEFT JOIN trenda_replay.entry_sl_geometry sg ON sg.entry_signal_id = es.id
WHERE es.symbol = 'EURUSD'
  AND es.sl_model_version = 'CHECK_GEO'
  AND es.signal_time >= '2026-01-01';
```
Expected: signals = signals_with_geo.

---

## Pass B — LOWER Profile (LOWER_TF_CHECK, 15M entry)

### Config changes needed
```python
# config.py
SL_MODEL_VERSION = 'LOWER_TF_CHECK'
REPLAY_SYMBOLS   = ["EURUSD"]
REPLAY_START_DATE = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
REPLAY_END_DATE   = datetime(2026, 1, 19, 0, 0, 0, tzinfo=timezone.utc)
```
```
REPLAY_TF_PROFILE=LOWER  (env var)
```

### Run
```
cd data-retriever && python main.py
```

### Sanity Queries — Pass B

**B1. Signal time distribution (minutes 0/15/30/45 must all be present)**
```sql
SELECT
    EXTRACT(MINUTE FROM signal_time) AS minute,
    COUNT(*) AS cnt
FROM trenda_replay.entry_signal
WHERE symbol = 'EURUSD'
  AND sl_model_version = 'LOWER_TF_CHECK'
  AND signal_time >= '2026-01-01'
GROUP BY 1
ORDER BY 1;
```
Expected: rows for minute IN (0, 15, 30, 45). If only minute=0 appears,
`find_index_by_time` is still hitting the 1H store (regression).

**B2. Outcome coverage — broken down by minute (the critical regression check)**
```sql
SELECT
    EXTRACT(MINUTE FROM signal_time) AS minute,
    COUNT(*) AS total,
    SUM(CASE WHEN outcome_computed THEN 1 ELSE 0 END) AS computed,
    ROUND(100.0 * SUM(CASE WHEN outcome_computed THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct
FROM trenda_replay.entry_signal
WHERE symbol = 'EURUSD'
  AND sl_model_version = 'LOWER_TF_CHECK'
  AND signal_time >= '2026-01-01'
GROUP BY 1
ORDER BY 1;
```
Expected: pct = 100.0 for ALL minutes (0, 15, 30, 45).
**If :15/:30/:45 signals have pct < 100, the `get_entry_candles()` fix did not apply.**

**B3. ATR sanity (15M ATR must be smaller than 1H ATR from Pass A)**
```sql
SELECT
    ROUND(AVG(atr_tf)::NUMERIC, 6) AS avg_atr,
    ROUND(MIN(atr_tf)::NUMERIC, 6) AS min_atr,
    ROUND(MAX(atr_tf)::NUMERIC, 6) AS max_atr
FROM trenda_replay.entry_signal
WHERE symbol = 'EURUSD'
  AND sl_model_version = 'LOWER_TF_CHECK'
  AND signal_time >= '2026-01-01';
```
Expected: avg_atr < DEFAULT avg_atr from A3 (15M ATR ≈ 25–50% of 1H ATR).
**If LOWER avg_atr ≈ DEFAULT avg_atr, the dual-ATR split in signal_detector.py failed.**

**B4. Path extremes — bar_index scale (120 bars = 30 hours at 15M)**
```sql
SELECT
    COUNT(DISTINCT es.id)         AS signals,
    COUNT(pe.entry_signal_id)     AS path_rows,
    MAX(pe.bar_index)             AS max_bar_index
FROM trenda_replay.entry_signal es
JOIN trenda_replay.signal_path_extremes pe ON pe.entry_signal_id = es.id
WHERE es.symbol = 'EURUSD'
  AND es.sl_model_version = 'LOWER_TF_CHECK'
  AND es.signal_time >= '2026-01-01';
```
Expected: max_bar_index = 120. Each bar = 15 minutes, so 120 bars = 30 hours.

**B5. Geometry lookahead check (verify signal candle range is 15M-sized)**
```sql
-- signal_candle_range_atr in 15M context should be SMALLER than in 1H context
-- (a 15M candle range is naturally smaller than a 1H candle range in ATR units)
SELECT
    sl_model_version,
    ROUND(AVG(sg.signal_candle_range_atr)::NUMERIC, 4) AS avg_candle_range_atr,
    ROUND(AVG(sg.signal_candle_body_atr)::NUMERIC, 4)  AS avg_candle_body_atr
FROM trenda_replay.entry_signal es
JOIN trenda_replay.entry_sl_geometry sg ON sg.entry_signal_id = es.id
WHERE es.symbol = 'EURUSD'
  AND es.signal_time >= '2026-01-01'
GROUP BY es.sl_model_version;
```
Expected: LOWER_TF_CHECK `avg_candle_range_atr` ≈ 0.1–0.5 (small 15M bars).
If it shows values similar to or larger than CHECK_GEO, the geometry is
still reading the 1H candle (lookahead bug not fixed).

**B6. Exit simulation coverage**
```sql
SELECT
    COUNT(DISTINCT entry_signal_id) AS signals_with_sims,
    COUNT(*) AS total_sim_rows
FROM trenda_replay.exit_simulation
WHERE entry_signal_id IN (
    SELECT id FROM trenda_replay.entry_signal
    WHERE symbol = 'EURUSD'
      AND sl_model_version = 'LOWER_TF_CHECK'
      AND signal_time >= '2026-01-01'
);
```
Expected: signals_with_sims = total signals from B2. Previously, ~75% had no sims.

---

## Cross-Profile Comparison

**C1. Compare outcome window in real time**
```sql
-- For DEFAULT (1H): 120 bars = 120 hours ≈ 5 days
-- For LOWER (15M):  120 bars = 30 hours  ≈ 1.25 days
-- Verify via bars_to_mfe distribution
SELECT
    es.sl_model_version,
    ROUND(AVG(so.bars_to_mfe), 1)  AS avg_bars_to_mfe,
    ROUND(AVG(so.bars_to_mae), 1)  AS avg_bars_to_mae,
    ROUND(AVG(so.mfe_atr), 4)      AS avg_mfe_atr,
    ROUND(AVG(so.mae_atr), 4)      AS avg_mae_atr
FROM trenda_replay.entry_signal es
JOIN trenda_replay.signal_outcome so ON so.entry_signal_id = es.id
WHERE es.symbol = 'EURUSD'
  AND es.signal_time >= '2026-01-01'
GROUP BY es.sl_model_version;
```
Both rows should show avg_bars_to_mfe and avg_bars_to_mae between 1 and 120.
MFE/MAE ATR values normalized to their respective TF ATR — not directly comparable.

---

## Pass/Fail Criteria

| Check | Pass Condition |
|-------|----------------|
| A1 — DEFAULT signal minutes | Only minute = 0 |
| A2 — DEFAULT outcome coverage | ≥ 95% (near end_date may be pending) |
| A3 — DEFAULT ATR range | 0.0003–0.0015 |
| A4 — DEFAULT path bar_index | max = 120 |
| A5 — DEFAULT exit sims | Every signal has rows |
| A6 — DEFAULT geometry | signals = signals_with_geo |
| B1 — LOWER signal minutes | All of 0, 15, 30, 45 present |
| B2 — LOWER outcome by minute | 100% for ALL minutes |
| B3 — LOWER ATR smaller | LOWER avg < DEFAULT avg |
| B4 — LOWER path bar_index | max = 120 |
| B5 — LOWER candle range | avg_candle_range_atr < DEFAULT value |
| B6 — LOWER exit sims | signals_with_sims = total signals |

---

## Reporting
Report all query results. For any failed check, copy the exact output and note
which invariant was violated. Do NOT attempt fixes — document and stop.

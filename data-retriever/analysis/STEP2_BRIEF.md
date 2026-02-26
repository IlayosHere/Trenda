# Agent Brief — STEP 2: Approach Candle Feature Backfill + Analysis

## Context

All existing pre-entry parameters (~28 features from pre_entry_context_v2 + entry_signal)
have been tested and show near-zero predictive power for win/loss outcome.

**New hypothesis**: The quality of the approach to the AOI — what price was doing in the
3–5 candles BEFORE the retest candle — may be structurally predictive in a way that
snapshot-at-signal-time data cannot capture.

### Signal anatomy reminder

For `is_break_candle_last = TRUE` (the only signals we analyze):

```
[approach candles]  →  [retest candle]  →  [0-N inside-AOI candles]  →  [break/signal candle]
  NOT stored yet         opens outside       stay in zone                  = signal_time
                         closes INTO AOI
```

The retest candle time = `signal_time - (bars_between_retest_and_break + 1) hours`
The 3 approach candles = the 3 1H candles immediately before the retest candle.

**The retest direction is fixed by pattern construction:**
- Bullish setup: retest candle drops from ABOVE into demand zone (counter-trend pullback)
- Bearish setup: retest candle rises from BELOW into supply zone (counter-trend bounce)

So "approach" always means counter-trend price movement toward the AOI.

---

## Your Task — Phase Structure

**This is a 3-phase task. You MUST complete Phase 1 interactively with the user before coding.**

### Phase 1: Propose features and get user confirmation

Before writing any code, do the following:
1. Read the "Proposed Features" section below
2. Ask the user to confirm, add, or remove features
3. Only proceed to Phase 2 after the user approves the feature list

### Phase 2: Write the backfill script
- Fetch raw 1H candles from MT5 for each signal
- Compute confirmed features
- Store in new DB table `trenda_replay.approach_context`

### Phase 3: Run correlation stability analysis
- Apply the same median-split year-by-year stability test (same logic as `correlation_stability.py`)
- Report which features (if any) are structurally predictive

---

## Proposed Features (present these to user for confirmation)

Present this list to the user and ask: "Should I add, remove, or change any of these before starting?"

### For each signal, looking at the 3 candles immediately before the retest candle:

**A. Approach net move**
`approach_3bar_net_atr` — net price move of those 3 candles in the approach direction, in ATR.
- For bearish: `(close[retest-1] - close[retest-4]) / atr_1h` — positive = price moved up (toward supply zone)
- For bullish: `(close[retest-4] - close[retest-1]) / atr_1h` — positive = price moved down (toward demand zone)
- High value = sharp, momentum-driven approach to the AOI

**B. Approach candle size**
`approach_3bar_avg_range_atr` — average (high-low) of the 3 approach candles / atr_1h
- Large value = strong-bodied impulse approach
- Small value = indecisive / compressed candles

**C. Approach directional consistency**
`approach_3bar_direction_count` — how many of the 3 candles had their body in the approach direction (INTEGER 0–3)
- For bearish: how many candles had close > open (bullish body, moving up)?
- For bullish: how many candles had close < open (bearish body, moving down)?
- 3 = perfectly clean approach; 0 = all candles against the approach direction

**D. Same metrics for 5 bars**
`approach_5bar_net_atr`, `approach_5bar_avg_range_atr`, `approach_5bar_direction_count`
- Wider window to capture approaches that take longer to reach the AOI

**E. Approach distance (how far price came)**
`approach_distance_atr` — how far was price from the AOI near edge at `retest_time - 3h`, in ATR.
- For bearish: `(aoi_lower - low[retest-4]) / atr_1h` — how far below the supply zone was price 3 bars before
- For bullish: `(high[retest-4] - aoi_upper) / atr_1h` — how far above the demand zone was price

---

## Data Source

**Raw 1H candles are NOT in the DB.** They must be fetched from MT5.

Use `externals/data_fetcher.py` to fetch historical 1H OHLCV data for each symbol.
The data_fetcher is the existing MT5 interface used during replay.

Approach for the backfill:
1. Connect to MT5 (same initialization as the replay system)
2. Group signals by symbol to batch candle fetches
3. For each symbol: fetch all 1H candles covering the full signal date range
4. For each signal: extract the 5 candles before the retest candle from the in-memory DataFrame

This avoids N individual MT5 calls (one per signal). Load all candles for a symbol once,
then slice per signal.

---

## New DB Table

```sql
CREATE TABLE IF NOT EXISTS trenda_replay.approach_context (
    entry_signal_id          INTEGER PRIMARY KEY
        REFERENCES trenda_replay.entry_signal(id) ON DELETE CASCADE,
    approach_3bar_net_atr         NUMERIC,
    approach_3bar_avg_range_atr   NUMERIC,
    approach_3bar_direction_count INTEGER,
    approach_5bar_net_atr         NUMERIC,
    approach_5bar_avg_range_atr   NUMERIC,
    approach_5bar_direction_count INTEGER,
    approach_distance_atr         NUMERIC,
    created_at               TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
```

Add or remove columns depending on what the user confirms in Phase 1.

---

## Backfill Script

`data-retriever/replay/backfill_approach_context.py`

Structure:
1. Load all entry signals: `(id, symbol, signal_time, direction, atr_1h, aoi_low, aoi_high, bars_between_retest_and_break)` — only where `is_break_candle_last = TRUE` AND `sl_model_version = 'CHECK_GEO'`
2. Deduplicate by `(symbol, signal_time)` — approach candle data is SL-model independent
3. Group by symbol
4. For each symbol: init MT5, fetch all 1H candles for full date range (2019–2025)
5. For each signal in that symbol: compute features from sliced candle window
6. INSERT into `trenda_replay.approach_context` with `ON CONFLICT DO NOTHING`
7. Log progress per symbol

Use `psycopg2.connect(**POSTGRES_DB)` for DB writes.

---

## Analysis Script

`data-retriever/analysis/approach_stability.py`

Apply the same correlation stability analysis as `correlation_stability.py`:
- Load the new features from `trenda_replay.approach_context`
- Join to the base dataset (same SQL as all other analysis scripts)
- For each feature × cell × year: median split → win% top vs bottom half
- Compute stability score (0–7 years consistent direction) and avg lift (pp)

Output format: same as `correlation_stability.py` — ranked table per cell.

Interpretation thresholds (same as before):
- Stability 7/7 + lift >= 3pp → structural signal
- Stability 6/7 + lift >= 2pp → credible
- Stability <= 5/7 → noise

---

## Technical Constraints

- DB connection: `psycopg2.connect(**POSTGRES_DB)` with cursor
- Cast all NUMERIC columns to float
- `pd.to_datetime(..., utc=True)`
- No `print()` for logging — use `get_logger(__name__)`
- Strict PEP 8, type hints, snake_case
- MT5 must be connected before candle fetches — use existing MT5 init pattern from `externals/data_fetcher.py`

## File Locations

```
data-retriever/
  replay/
    backfill_approach_context.py   <- NEW
  analysis/
    approach_stability.py          <- NEW
  externals/
    data_fetcher.py                <- existing MT5 interface
  configuration/
    db_config.py                   <- POSTGRES_DB dict
  logger.py                        <- get_logger(name)
```

## Run Commands

```bash
# Phase 2 — backfill (run once, idempotent)
cd data-retriever && python replay/backfill_approach_context.py

# Phase 3 — analysis
cd data-retriever && python analysis/approach_stability.py
```
